"""Conditional noise-budget sensitivity without estimating an unknown noise cap.

The v1 exact certificate implementation is preserved. This wrapper checks the
same fixed decision under a second, explicitly supplied componentwise larger
history budget. Set inclusion transfers an upper-endpoint safe certificate to
each nonempty smaller compatible set; it cannot validate the supplied cap,
features, feasible sets, or parameter box.
"""
import copy
import time

from inverse_certified import analyze_compatibility, budget_for, rational


def _envelope_config(data):
    config = data.get("certification")
    if not isinstance(config, dict) or "sensitivity" not in config:
        return None
    sensitivity = config["sensitivity"]
    if not isinstance(sensitivity, dict):
        raise ValueError("certification.sensitivity must be an object")
    lower_noise = config.get("noise")
    upper_noise = sensitivity.get("upperNoise")
    if not isinstance(lower_noise, dict) or lower_noise.get("kind") != "absolute":
        raise ValueError("Sensitivity requires an absolute nominal noise model")
    if not isinstance(upper_noise, dict) or upper_noise.get("kind") != "absolute":
        raise ValueError("sensitivity.upperNoise must explicitly declare absolute budgets")
    for noise in (lower_noise, upper_noise):
        if ("budget" in noise) == ("budgets" in noise):
            raise ValueError("Declare exactly one of budget or budgets for each noise model")
        if "budgets" in noise and not isinstance(noise["budgets"], dict):
            raise ValueError("Per-history budgets must be an object")
    for sample in data["samples"]:
        if budget_for(upper_noise, sample["id"]) < budget_for(lower_noise, sample["id"]):
            raise ValueError("Sensitivity upper budgets must be >= nominal budgets for every history")
    seconds = float(rational(sensitivity.get("maxSeconds", config.get("maxSeconds", 20))))
    calls = sensitivity.get("maxOracleCalls", config.get("maxOracleCalls", 200))
    if not 0 < seconds <= 120:
        raise ValueError("Sensitivity maxSeconds must be in (0,120]")
    if isinstance(calls, bool) or not isinstance(calls, int) or not 0 <= calls <= 10000:
        raise ValueError("Invalid sensitivity maxOracleCalls")
    return {"upperNoise": copy.deepcopy(upper_noise), "maxSeconds": seconds,
            "maxOracleCalls": calls}


def analyze_with_sensitivity(data, point_theta=None):
    """Preserve the nominal certificate and add an explicit upper-budget check."""
    started = time.monotonic()
    envelope = _envelope_config(data)
    nominal = analyze_compatibility(data, point_theta)
    nominal["assumptionAudit"] = {
        "noiseBudget": "declared_not_independently_verified",
        "modelStructure": "declared_not_independently_verified",
        "trainingFitValidatesNoiseBudget": False,
        "note": "误差上限、参数框和候选特征来自输入，程序没有证明它们符合真实情况；训练拟合好不能代替这项依据。",
    }
    original = nominal.get("decisionCertificate", {})
    original_status = original.get("status", "unresolved")
    guidance = {
        "status": "conditional_safe" if original_status == "safe" else original_status,
        "scope": "nominal_budget_only",
        "note": "当前结论仅针对输入的单个误差假设；尚未检查误差估小后的变化，也没有验证误差上限本身。",
        "chosenDecision": original.get("chosenDecision"),
    }
    if envelope is None:
        nominal["noiseSensitivity"] = {
            "schema": "noise-budget-sensitivity.v1", "status": "not_requested",
            "note": "未声明敏感性上限，未自动放大误差或猜测真实误差。",
            "upperNoise": None, "rangeSafe": False,
        }
        nominal["decisionGuidance"] = guidance
        return nominal

    expanded = copy.deepcopy(data)
    expanded["certification"].pop("sensitivity", None)
    expanded["certification"]["noise"] = envelope["upperNoise"]
    expanded["certification"]["maxSeconds"] = envelope["maxSeconds"]
    expanded["certification"]["maxOracleCalls"] = envelope["maxOracleCalls"]
    upper_result = analyze_compatibility(expanded, point_theta)
    upper = upper_result.get("decisionCertificate", {})
    fixed = (bool(original.get("chosenDecision"))
             and original.get("chosenDecision") == upper.get("chosenDecision"))
    upper_status = upper.get("status", "unresolved")
    status = "unresolved"
    note = "上限处尚无足够证据，不能给整个误差包络安全保证。"
    if fixed and upper_status == "safe":
        status = "stable_safe"
        note = ("在声明上限、模型和参数框正确的前提下，同一方案满足损失阈值；"
                "该结论覆盖每个不超过上限的非空相容集合，不证明较小预算都与历史相容。")
    elif fixed and upper_status == "risk_witness":
        status = "sensitive" if original_status == "safe" else "risk_in_envelope"
        note = ("较宽误差假设下已找到超过阈值的相容参数，不能沿用较紧预算的安全结论；"
                "这不表示真实参数一定有风险，也不表示每个较小预算都不安全。")
    elif fixed and upper_status == "incompatible":
        status = "incompatible"
        note = "即使使用声明上限，历史仍与参数框和特征不相容；不能对空集合签发保证。"
    elif not fixed:
        note = "没有取得两个端点的同一方案，未作跨预算保证；各端点结果仅供单独查看。"
    guidance.update(
        scope="declared_upper_budget",
        status=("conditional_safe" if status == "stable_safe" else
                "risk_witness" if status in ("sensitive", "risk_in_envelope") else
                "incompatible" if status == "incompatible" else "unresolved"),
        note=note,
    )
    nominal["noiseSensitivity"] = {
        "schema": "noise-budget-sensitivity.v1", "status": status,
        "nominalStatus": original_status, "upperStatus": upper_status,
        "upperNoise": envelope["upperNoise"], "fixedDecisionVerified": fixed,
        "rangeSafe": status == "stable_safe",
        "upperCertificate": upper, "upperAnalysis": upper_result,
        "nesting": "Componentwise upper budgets enlarge the compatible set; all other model inputs and the candidate remain fixed.",
        "criticalBudgetEstimated": False, "budgetUpperBoundValidated": False,
        "note": note,
        "resources": {
            "nominal": nominal.get("resources"),
            "upper": upper_result.get("resources"),
            "totalElapsedMs": round((time.monotonic() - started) * 1000),
            "budgetContract": "Two separately budgeted complete checks; cooperative limits. No shared total deadline.",
        },
    }
    nominal["decisionGuidance"] = guidance
    return nominal
