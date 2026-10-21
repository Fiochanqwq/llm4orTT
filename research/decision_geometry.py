"""Exact two-variable LP geometry; no solver, sampling, or source execution.

IR variables are continuous and nonnegative. Numeric floats are interpreted
as their decimal representation, never as binary floating-point fractions.
All public results are JSON serializable and rational values are strings.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as F
from itertools import combinations
import math
from typing import Any

Point = tuple[F, F]
Row = tuple[F, F, F]
MAX_ROWS = 32
MAX_RATIONAL_BITS = 128


def rational(value: Any) -> F:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, F)):
        raise ValueError("coefficients must be finite numbers or rational strings")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite coefficient")
    if isinstance(value, str) and len(value) > 128:
        raise ValueError("coefficient string too long")
    try:
        result = value if isinstance(value, F) else F(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("invalid rational coefficient") from exc
    if max(abs(result.numerator).bit_length(), result.denominator.bit_length()) > MAX_RATIONAL_BITS:
        raise ValueError("coefficient exceeds rational size limit")
    return result


def _pair(value: Any) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("expected exactly two coefficients")
    return rational(value[0]), rational(value[1])


def _dot(a: Point, x: Point) -> F:
    return a[0] * x[0] + a[1] * x[1]


def _s(point: Point) -> list[str]:
    return [str(point[0]), str(point[1])]


def _row_normalize(row: Row) -> Row:
    # Positive scaling preserves <=; normalize also makes witnesses scale invariant.
    scale = abs(row[0]) + abs(row[1])
    if not scale:
        scale = abs(row[2]) or F(1)
    return tuple(v / scale for v in row)


@dataclass(frozen=True)
class LP2:
    sense: str
    objective: Point
    rows: tuple[Row, ...]


def compile_model(ir: dict) -> LP2:
    if not isinstance(ir, dict):
        raise ValueError("model must be an object")
    required = {"sense", "objective", "constraints"}
    missing = required - ir.keys()
    extra = ir.keys() - required
    if missing:
        raise ValueError("missing model fields: " + ", ".join(sorted(missing)))
    if extra:
        raise ValueError("unknown model fields: " + ", ".join(sorted(map(str, extra))))
    if ir["sense"] not in ("min", "max"):
        raise ValueError("sense must be min or max")
    objective = _pair(ir.get("objective"))
    raw = ir.get("constraints")
    if not isinstance(raw, list) or len(raw) > MAX_ROWS:
        raise ValueError("constraints must be a list of at most 32 rows")
    rows: list[Row] = [(F(-1), F(0), F(0)), (F(0), F(-1), F(0))]
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"constraint {index} must be an object")
        required_row = {"a", "op", "b"}
        missing = required_row - item.keys()
        extra = item.keys() - required_row
        if missing:
            raise ValueError(f"constraint {index} missing fields: " + ", ".join(sorted(missing)))
        if extra:
            raise ValueError(f"constraint {index} unknown fields: " + ", ".join(sorted(map(str, extra))))
        if item["op"] not in ("<=", ">=", "="):
            raise ValueError("constraint operator must be <=, >=, or =")
        a = _pair(item.get("a"))
        b = rational(item.get("b"))
        row = (a[0], a[1], b)
        if item["op"] in ("<=", "="):
            rows.append(row)
        if item["op"] in (">=", "="):
            rows.append(tuple(-v for v in row))
    return LP2(ir["sense"], objective, tuple(sorted(set(map(_row_normalize, rows)))))


def _feasible(rows: tuple[Row, ...], x: Point) -> bool:
    return all(a * x[0] + b * x[1] <= c for a, b, c in rows)


def _geometry(rows: tuple[Row, ...]) -> tuple[tuple[Point, ...], tuple[Point, ...]]:
    vertices = set()
    for r, s in combinations(rows, 2):
        det = r[0] * s[1] - r[1] * s[0]
        if det:
            x = ((r[2] * s[1] - r[1] * s[2]) / det,
                 (r[0] * s[2] - r[2] * s[0]) / det)
            if _feasible(rows, x):
                vertices.add(x)
    if not vertices:
        # The explicit nonnegative domain excludes lines, so any nonempty
        # feasible polyhedron has an extreme point, including lower dimensions.
        return (), ()
    rays = set()
    for a, b, _ in rows:
        for d in ((b, -a), (-b, a)):
            scale = abs(d[0]) + abs(d[1])
            if scale and all(u * d[0] + v * d[1] <= 0 for u, v, _ in rows):
                rays.add((d[0] / scale, d[1] / scale))
    return tuple(sorted(vertices)), tuple(sorted(rays))


def _analysis(model: LP2) -> dict:
    vertices, rays = _geometry(model.rows)
    result = {"vertices": vertices, "rays": rays, "optimal_vertices": (),
              "optimal_rays": (), "value": None}
    if not vertices:
        return dict(result, status="infeasible")
    direction = F(1) if model.sense == "min" else F(-1)
    if any(direction * _dot(model.objective, d) < 0 for d in rays):
        return dict(result, status="unbounded")
    best = min(direction * _dot(model.objective, x) for x in vertices)
    return dict(result, status="optimal", value=direction * best,
                optimal_vertices=tuple(x for x in vertices if direction * _dot(model.objective, x) == best),
                optimal_rays=tuple(d for d in rays if _dot(model.objective, d) == 0))


def _public_analysis(model: LP2, result: dict) -> dict:
    return {"status": result["status"], "sense": model.sense,
            "objective": _s(model.objective),
            "value": None if result["value"] is None else str(result["value"]),
            "vertices": [_s(x) for x in result["vertices"]],
            "recession_rays": [_s(x) for x in result["rays"]],
            "optimal_face": {"vertices": [_s(x) for x in result["optimal_vertices"]],
                             "recession_rays": [_s(x) for x in result["optimal_rays"]]}}


def analyze_model(ir: dict) -> dict:
    model = compile_model(ir)
    return _public_analysis(model, _analysis(model))


def _face_rows(model: LP2, result: dict) -> tuple[Row, ...]:
    if result["status"] != "optimal":
        return ((F(0), F(0), F(-1)),)
    a, b = model.objective
    value = result["value"]
    return model.rows + (_row_normalize((a, b, value)), _row_normalize((-a, -b, -value)))


def _objective_order_equal(left: LP2, right: LP2, analysis: dict) -> bool:
    """Equality of the complete weak order on one common feasible polyhedron.

    Differences of vertices and recession rays span its affine hull. Objective
    restrictions must be the same up to a positive scale, or both zero.
    """
    vertices = analysis["vertices"]
    if not vertices:
        return True
    anchor = vertices[0]
    span = [(v[0] - anchor[0], v[1] - anchor[1]) for v in vertices[1:]] + list(analysis["rays"])
    lsign = 1 if left.sense == "min" else -1
    rsign = 1 if right.sense == "min" else -1
    lvalues = [lsign * _dot(left.objective, d) for d in span]
    rvalues = [rsign * _dot(right.objective, d) for d in span]
    index = next((i for i, value in enumerate(lvalues) if value), None)
    if index is None:
        return not any(rvalues)
    factor = rvalues[index] / lvalues[index]
    return factor > 0 and all(rv == factor * lv for lv, rv in zip(lvalues, rvalues))


def _inclusion_witnesses(vertices: tuple[Point, ...], rays: tuple[Point, ...],
                         target_rows: tuple[Row, ...], kind: str, source: str,
                         target: str) -> list[dict]:
    result = []
    for row in target_rows:
        a = (row[0], row[1])
        candidates: dict[Point, tuple[str, Point | None, F | None]] = {}
        for x in vertices:
            if _dot(a, x) > row[2]:
                candidates[x] = ("vertex", None, None)
            for d in rays:
                slope = _dot(a, d)
                if slope > 0:
                    # A finite point with strictly positive exact violation.
                    t = max(F(0), (row[2] - _dot(a, x)) / slope) + 1 / slope
                    y = (x[0] + t * d[0], x[1] + t * d[1])
                    candidates.setdefault(y, ("ray", d, t))
        for x, (origin, d, t) in candidates.items():
            violation = _dot(a, x) - row[2]
            norm = abs(a[0]) + abs(a[1]) or F(1)
            result.append({"kind": kind, "source": source, "target": target,
                           "point": _s(x), "origin": origin,
                           "target_row": {"a": _s(a), "op": "<=", "b": str(row[2])},
                           "violation": str(violation), "normalized_violation": str(violation / norm),
                           "ray": None if d is None else _s(d),
                           "ray_step": None if t is None else str(t)})
    return result


def compare_models(left_ir: dict, right_ir: dict) -> dict:
    """Compare feasible sets and full minimizer/maximizer sets exactly.

    An unbounded or infeasible model has no attained optimal face. Equivalence
    additionally requires equal statuses; two unbounded models with the same
    feasible set are equivalent under this status/attained-optima contract.
    The witnesses use only these two models, never external reference labels.
    """
    left, right = compile_model(left_ir), compile_model(right_ir)
    la, ra = _analysis(left), _analysis(right)
    witnesses = []
    for model, info, other, other_info, source, target in (
            (left, la, right, ra, "left", "right"),
            (right, ra, left, la, "right", "left")):
        witnesses.extend(_inclusion_witnesses(info["vertices"], info["rays"], other.rows,
                                              "feasibility", source, target))
        witnesses.extend(_inclusion_witnesses(info["optimal_vertices"], info["optimal_rays"],
                                              _face_rows(other, other_info), "optimal_face", source, target))
    witnesses.sort(key=lambda w: (-F(w["normalized_violation"]), w["kind"], w["source"],
                                 tuple(F(v) for v in w["point"]), str(w["target_row"])))
    feasible_equal = not any(w["kind"] == "feasibility" for w in witnesses)
    faces_equal = not any(w["kind"] == "optimal_face" for w in witnesses)
    statuses_equal = la["status"] == ra["status"]
    return {"equivalent": feasible_equal and faces_equal and statuses_equal,
            "feasible_sets_equal": feasible_equal, "optimal_faces_equal": faces_equal,
            "objective_order_equal": _objective_order_equal(left, right, la) if feasible_equal else None,
            "statuses_equal": statuses_equal, "left": _public_analysis(left, la),
            "right": _public_analysis(right, ra), "witnesses": witnesses}


def disagreement_witnesses(left_ir: dict, right_ir: dict) -> list[dict]:
    """All enumerated finite separating candidates, ranked by normalized violation."""
    return compare_models(left_ir, right_ir)["witnesses"]
