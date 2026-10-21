"""Bounded-noise certificates for small, fully enumerated discrete decisions.

The old point estimator remains separate. This module never reads hidden truth.
LPs propose parameters and dual multipliers; exact rational arithmetic checks
membership and weak-duality bounds. Missing computation yields unresolved.
This is a reference implementation, not a claim of research novelty.
"""
import itertools
import json
import math
import sys
import time
from fractions import Fraction as Q
from pathlib import Path

import highspy as hs
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inverse import validate


def rational(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite numeric value")
    return Q(str(value))


def scalar(a, b):
    return sum((x * y for x, y in zip(a, b)), Q(0))


def outward(value, upper):
    """Serialize a rational bound without rounding it inward."""
    result = float(value)
    if upper and Q.from_float(result) < value:
        result = math.nextafter(result, math.inf)
    if not upper and Q.from_float(result) > value:
        result = math.nextafter(result, -math.inf)
    return result


def terms_value(terms, decision):
    return sum((rational(v) * decision[n] for n, v in terms.items()), Q(0))


def affine(sample, decision, hypotheses):
    base = terms_value(sample["model"]["objective"], decision)
    features = []
    for h in hypotheses:
        feature = sample["features"][h["id"]]
        value = terms_value(feature["terms"], decision)
        if feature.get("kind") == "soft":
            value -= rational(feature["rhs"])
            if feature["sense"] == ">=":
                value = -value
            value = max(Q(0), value)
        features.append(value)
    return base, tuple(features)


def enumerate_actions(sample, hypotheses, limit, deadline):
    """Enumerate the complete original feasible set, including hinge costs."""
    domains, names, count = [], [], 1
    for var in sample["model"]["variables"]:
        if var["type"] not in ("binary", "integer"):
            raise NotImplementedError("本轮证书仅支持有界整数决策；连续规划仍保留旧求解功能。")
        lo, hi = var.get("lower"), var.get("upper")
        if var["type"] == "binary":
            lo, hi = max(0, lo if lo is not None else 0), min(1, hi if hi is not None else 1)
        if lo is None or hi is None:
            raise NotImplementedError("整数变量需要显式有限上下界。")
        lo, hi = math.ceil(lo), math.floor(hi)
        domain = range(lo, hi + 1)
        count *= len(domain)
        if count > limit:
            raise NotImplementedError("完整枚举超过声明上限；未截取部分方案冒充完整证书。")
        names.append(var["name"])
        domains.append(domain)
    actions = []
    for values in itertools.product(*domains):
        if time.monotonic() > deadline:
            raise TimeoutError("完整动作枚举耗尽时间预算。")
        decision = dict(zip(names, values))
        feasible = True
        for row in sample["model"]["constraints"]:
            value, rhs = terms_value(row["terms"], decision), rational(row["rhs"])
            if ((row["sense"] == "=" and value != rhs)
                or (row["sense"] == "<=" and value > rhs)
                or (row["sense"] == ">=" and value < rhs)):
                feasible = False
                break
        if feasible:
            actions.append({"decision": decision, "affine": affine(sample, decision, hypotheses)})
    if not actions:
        raise ValueError("决策可行域为空。")
    return actions


def exact_solve(rows, rhs, dimension):
    """Solve an independent square subsystem by rational Gaussian elimination."""
    pivots = {}
    for row, value in zip(rows, rhs):
        work = list(row) + [value]
        for col in sorted(pivots):
            scale = work[col]
            if scale:
                work = [x - scale * y for x, y in zip(work, pivots[col])]
        pivot = next((j for j in range(dimension) if work[j]), None)
        if pivot is None:
            continue
        divisor = work[pivot]
        work = [x / divisor for x in work]
        for col, old in list(pivots.items()):
            scale = old[pivot]
            if scale:
                pivots[col] = [x - scale * y for x, y in zip(old, work)]
        pivots[pivot] = work
        if len(pivots) == dimension:
            return tuple(pivots[j][-1] for j in range(dimension))
    return None


class CompatibleSet:
    def __init__(self, box, histories, max_seconds=20, max_calls=200, started=None):
        self.box = box
        self.histories = histories
        self.started = started if started is not None else time.monotonic()
        self.deadline = self.started + max_seconds
        self.max_calls = max_calls
        self.calls = 0
        self.lp_calls = 0
        self.rows = []
        self.row_keys = set()
        self.witnesses = []
        self.empty = False
        self.trace = []
        self.dimension = len(box)

    def remaining(self):
        return self.calls < self.max_calls and time.monotonic() < self.deadline

    def add_row(self, a, b):
        key = (tuple(a), b)
        if key not in self.row_keys:
            self.row_keys.add(key)
            self.rows.append(key)
            return True
        return False

    def box_support(self, objective):
        return sum((max(v * lo, v * hi) for v, (lo, hi) in zip(objective, self.box)), Q(0))

    def inside_outer(self, theta):
        return (theta is not None
                and all(lo <= v <= hi for v, (lo, hi) in zip(theta, self.box))
                and all(scalar(a, theta) <= b for a, b in self.rows))

    def membership(self, theta):
        """One exact, complete history separation call; never sample opponents."""
        self.calls += 1
        violations = []
        for history in self.histories:
            worst = None
            for a, b in history:
                gap = scalar(a, theta) - b
                if gap > 0 and (worst is None or gap > worst[0]):
                    worst = (gap, a, b)
            if worst:
                violations.append(worst)
        if not violations:
            if theta not in self.witnesses:
                self.witnesses.append(theta)
            return True
        for _, a, b in violations:
            self.add_row(a, b)
        return False

    def dual_upper(self, objective, multipliers):
        """For ANY nonnegative y: support <= y*b + support_box(q-A^T*y)."""
        residual = list(objective)
        value = Q(0)
        for (a, b), y in zip(self.rows, multipliers):
            y = max(Q(0), y)
            value += y * b
            residual = [r - y * coefficient for r, coefficient in zip(residual, a)]
        return value + self.box_support(residual)

    def reconstruct(self, values):
        candidates = [
            tuple(Q.from_float(float(v)).limit_denominator(10**9) for v in values),
            tuple(Q(str(float(v))) for v in values),
        ]
        # Recover a rational vertex from near-active constraints and variable bounds.
        active = list(self.rows)
        for j, (lo, hi) in enumerate(self.box):
            row = tuple(Q(int(i == j)) for i in range(self.dimension))
            active.extend([(row, lo), (row, hi)])
        active.sort(key=lambda row: abs(sum(float(a) * v for a, v in zip(row[0], values)) - float(row[1])))
        close = [row for row in active
                 if abs(sum(float(a) * v for a, v in zip(row[0], values)) - float(row[1]))
                 <= 1e-6 * max(1, abs(float(row[1])))]
        vertex = exact_solve([a for a, _ in close], [b for _, b in close], self.dimension)
        if vertex is not None:
            candidates.insert(0, vertex)
        return next((theta for theta in candidates if self.inside_outer(theta)), None)

    def lp_proposal(self, objective):
        solver = hs.Highs()
        for key, value in {"output_flag": False, "threads": 1,
                           "time_limit": max(.001, self.deadline - time.monotonic()),
                           "primal_feasibility_tolerance": 1e-9,
                           "dual_feasibility_tolerance": 1e-9}.items():
            solver.setOptionValue(key, value)
        lp = hs.HighsLp()
        lp.num_col_, lp.num_row_ = self.dimension, len(self.rows)
        lp.col_cost_ = [-float(v) for v in objective]
        lp.col_lower_ = [float(v[0]) for v in self.box]
        lp.col_upper_ = [float(v[1]) for v in self.box]
        lp.row_lower_ = [-hs.kHighsInf] * len(self.rows)
        lp.row_upper_ = [float(b) for _, b in self.rows]
        starts, indices, values = [0], [], []
        for a, _ in self.rows:
            for j, value in enumerate(a):
                if value:
                    indices.append(j)
                    values.append(float(value))
            starts.append(len(indices))
        lp.a_matrix_.format_ = hs.MatrixFormat.kRowwise
        lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = starts, indices, values
        solver.passModel(lp)
        solver.run()
        self.lp_calls += 1
        status = solver.getModelStatus()
        solution = solver.getSolution()
        upper = self.box_support(objective)
        if solution.dual_valid:
            y = [max(Q(0), -Q.from_float(float(v))) for v in solution.row_dual]
            upper = min(upper, self.dual_upper(objective, y))
        if status == hs.HighsModelStatus.kInfeasible:
            # An infeasible solver label alone is insufficient for a certificate.
            _, exists, ray = solver.getDualRay()
            if exists:
                for sign in (1, -1):
                    multipliers = [max(Q(0), sign * Q.from_float(float(v))) for v in ray]
                    if self.dual_upper([Q(0)] * self.dimension, multipliers) < 0:
                        self.empty = True
                        break
        theta = self.reconstruct(solution.col_value) if solution.value_valid else None
        return theta, upper, str(status)

    def support(self, objective):
        """Anytime max q*theta with exact lower witnesses and outer upper bound."""
        objective = tuple(objective)
        upper = self.box_support(objective)
        lower = max((scalar(objective, w) for w in self.witnesses), default=None)
        reason = "budget_limit"
        while self.remaining() and not self.empty:
            theta, proposed_upper, status = self.lp_proposal(objective)
            upper = min(upper, proposed_upper)
            if self.empty:
                reason = "incompatible"
                break
            if theta is None:
                reason = "unverified_solver_candidate"
                break
            member = self.membership(theta)
            lower = max((scalar(objective, w) for w in self.witnesses), default=None)
            self.trace.append({"lpStatus": status, "cuts": len(self.rows), "compatible": member,
                               "oracleCalls": self.calls})
            if member:
                reason = "complete" if lower == upper else "bounded"
                break
        return {"lower": lower, "upper": upper, "reason": reason}


def budget_for(noise, sample_id):
    if "budgets" in noise:
        if sample_id not in noise["budgets"]:
            raise ValueError("每条历史都需要一个事先声明的绝对误差预算。")
        value = noise["budgets"][sample_id]
    elif "budget" in noise:
        value = noise["budget"]
    else:
        raise ValueError("缺少绝对误差预算。")
    value = rational(value)
    if value < 0:
        raise ValueError("误差预算不能为负数。")
    return value


def analyze_compatibility(data, point_theta=None):
    started = time.monotonic()
    config = data.get("certification")
    answer = {"schema": "bounded-noise-certificate.v1", "modelCalls": 0,
              "meaning": "与逐条历史绝对误差预算相容的联合参数集合；不是置信区间。",
              "assumptions": ["真实权重在声明的参数框内", "每条历史满足声明的绝对费用误差预算",
                              "可行域和候选特征正确且完整"],
              "arithmetic": "decimal input interpreted as rationals; exact witness and weak-duality checks"}
    if config is None:
        return {**answer, "status": "budget_required",
                "note": "尚未声明历史允许的费用误差，不能从拟合残差推算真实价格保证。"}
    if not isinstance(config, dict) or not isinstance(config.get("noise"), dict):
        raise ValueError("certification.noise must be an object")
    noise = config["noise"]
    answer["noiseModel"] = noise
    if noise.get("kind") != "absolute":
        return {**answer, "status": "unsupported",
                "note": "本轮只实现声明的绝对费用误差；旧实验的相对误差未被偷偷改写。"}
    max_seconds = float(rational(config.get("maxSeconds", 20)))
    max_calls = config.get("maxOracleCalls", 200)
    max_assignments = config.get("maxAssignments", 4096)
    if not 0 < max_seconds <= 120:
        raise ValueError("maxSeconds must be in (0,120]")
    for value, upper, label in [(max_calls, 10000, "maxOracleCalls"), (max_assignments, 65536, "maxAssignments")]:
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= upper:
            raise ValueError("Invalid " + label)
    if max_assignments == 0:
        raise ValueError("maxAssignments must be positive")
    threshold = rational(config.get("threshold", 0))
    if threshold < 0:
        raise ValueError("threshold must be nonnegative")
    validate(data)
    hypotheses = data["hypotheses"]
    box = [(rational(h.get("lower", 0)), rational(h.get("upper", 20))) for h in hypotheses]
    histories, counts = [], []
    try:
        for sample in data["samples"]:
            actions = enumerate_actions(sample, hypotheses, max_assignments, started + max_seconds)
            observed = {n: rational(v) for n, v in sample["decision"].items()}
            if not any(all(observed[n] == v for n, v in a["decision"].items()) for a in actions):
                raise ValueError("历史决策不是已知可行整数方案。")
            ob, of = affine(sample, observed, hypotheses)
            delta = budget_for(noise, sample["id"])
            histories.append([(tuple(v - w for v, w in zip(of, f)), delta - ob + b)
                              for b, f in (a["affine"] for a in actions)])
            counts.append(len(actions))
        deployment = data.get("deployment", data["samples"][-1])
        # Validate deployment independently without allowing its decision into history.
        validate({**data, "samples": [deployment]})
        deployment_actions = enumerate_actions(deployment, hypotheses, max_assignments, started + max_seconds)
    except NotImplementedError as error:
        return {**answer, "status": "unsupported", "note": str(error)}
    except TimeoutError as error:
        return {**answer, "status": "partial", "note": str(error), "decisionCertificate": {
            "status": "unresolved", "lowerBound": None, "upperBound": None,
            "threshold": float(threshold), "note": "完整枚举未结束，没有输出安全证书。"}}
    engine = CompatibleSet(box, histories, max_seconds, max_calls, started)
    engine.support([Q(0)] * len(box))
    ranges = []
    for j, h in enumerate(hypotheses):
        if engine.empty:
            break
        direction = [Q(int(i == j)) for i in range(len(box))]
        hi = engine.support(direction)
        lo = engine.support([-v for v in direction])
        exact = hi["lower"] == hi["upper"] and lo["lower"] == lo["upper"]
        ranges.append({"id": h["id"], "label": h.get("label", h["id"]),
                       "lower": outward(-lo["upper"], False), "upper": outward(hi["upper"], True),
                       "status": "complete" if exact else "outer_bound",
                       "meaning": "联合相容集合的坐标外界，不能把整个盒当作联合集合"})
    default_theta = tuple((lo + hi) / 2 for lo, hi in box)
    if point_theta is not None:
        default_theta = tuple(rational(point_theta.get(h["id"], float(default_theta[i])))
                              for i, h in enumerate(hypotheses))
    chosen = min(range(len(deployment_actions)),
                 key=lambda i: deployment_actions[i]["affine"][0] +
                 scalar(deployment_actions[i]["affine"][1], default_theta))
    cb, cf = deployment_actions[chosen]["affine"]
    upper, lower, comparisons = Q(0), Q(0), []
    for action in deployment_actions:
        if engine.empty:
            break
        b, f = action["affine"]
        support = engine.support([v - w for v, w in zip(cf, f)])
        upper = max(upper, cb - b + support["upper"])
        if support["lower"] is not None:
            lower = max(lower, cb - b + support["lower"])
        comparisons.append({"rivalDecision": action["decision"],
                            "upperBound": outward(cb - b + support["upper"], True),
                            "lowerBound": outward(cb - b + support["lower"], False)
                            if support["lower"] is not None else None})
    has_witness = bool(engine.witnesses)
    # Never certify a vacuous empty uncertainty set or an unverified nonempty set.
    status = ("incompatible" if engine.empty else
              "safe" if has_witness and upper <= threshold else
              "risk_witness" if has_witness and lower > threshold else "unresolved")
    note = {"safe": "在列明的假设下，这个方案的最坏费用损失不超过阈值。",
            "risk_witness": "已找到相容价格，使这个方案超过损失阈值；不代表所有方案都不行。",
            "unresolved": "目前证据还不能判定此方案是否满足阈值。",
            "incompatible": "已核验当前历史与声明的参数框、误差预算不相容；未自动放宽预算。"}[status]
    answer.update(
        status="incompatible" if engine.empty else
        "complete" if has_witness and all(r["status"] == "complete" for r in ranges) and upper == lower else "partial",
        ranges=ranges,
        deploymentSource="provided_context" if "deployment" in data else "historical_context_replay",
        deploymentId=deployment["id"],
        historyActionCounts=counts, deploymentActionCount=len(deployment_actions),
        witnesses=[{h["id"]: str(v) for h, v in zip(hypotheses, w)} for w in engine.witnesses],
        decisionCertificate={"status": status, "lowerBound": outward(lower, False) if has_witness and not engine.empty else None,
                             "upperBound": outward(upper, True) if not engine.empty else None,
                             "threshold": float(threshold), "chosenDecision": deployment_actions[chosen]["decision"],
                             "note": note, "units": "absolute objective cost", "comparisons": comparisons,
                             "selectionRule": "existing point estimate, deterministic first tie"},
        resources={"oracleCalls": engine.calls, "lpCalls": engine.lp_calls, "cuts": len(engine.rows),
                   "maxOracleCalls": max_calls, "maxSeconds": max_seconds,
                   "elapsedMs": round((time.monotonic() - started) * 1000)},
        trace=engine.trace,
        note="完整动作枚举上的参考证书。旧数据只作开发回归；尚无大规模或新颖性结论。")
    return answer


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(analyze_compatibility(payload), ensure_ascii=True, allow_nan=False))
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=True))
        sys.exit(1)
