// Canonical certification UI restored from the verified 0.1.2 desktop bundle.
// This source is included by Vite; rebuilding no longer loses these controls.
import * as k from 'react/jsx-runtime';
function inverseCertificationNumber(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? String(value)
    : "尚无有效界";
}

function inverseCertificationInput({ draft, disabled, update }) {
  let data;
  try { data = JSON.parse(draft); } catch { return null; }
  const config = data.certification;
  const noise = config?.noise;
  const advanced = !!noise && (noise.kind !== "absolute" || !!noise.budgets);
  const upperNoise = config?.sensitivity?.upperNoise;
  const upperAdvanced = !!upperNoise && (upperNoise.kind !== "absolute" || !!upperNoise.budgets);
  const setBudget = value => {
    const next = { ...data };
    if (value === "") {
      delete next.certification;
    } else {
      const amount = Number(value);
      if (!Number.isFinite(amount) || amount < 0) return;
      next.certification = {
        ...(config || {}),
        noise: { kind: "absolute", budget: amount },
        threshold: config?.threshold ?? 0
      };
    }
    update(JSON.stringify(next, null, 2));
  };
  const setThreshold = value => {
    const amount = Number(value);
    if (value === "" || !Number.isFinite(amount) || amount < 0) return;
    update(JSON.stringify({
      ...data, certification: { ...config, threshold: amount }
    }, null, 2));
  };
  const setUpperBudget = value => {
    const next = { ...config };
    if (value === "") {
      delete next.sensitivity;
    } else {
      const amount = Number(value);
      if (!Number.isFinite(amount) || amount < 0) return;
      next.sensitivity = {
        ...(config.sensitivity || {}),
        upperNoise: { kind: "absolute", budget: amount }
      };
    }
    update(JSON.stringify({ ...data, certification: next }, null, 2));
  };
  return (0, k.jsxs)("details", {
    className: "inverse-data inverse-certification-input",
    children: [
      (0, k.jsx)("summary", { children: "决策保证 · 先明确历史误差上限" }),
      (0, k.jsx)("p", {
        className: "inverse-note",
        children: "这里的误差是“历史方案比当时最好方案多花多少钱”，不是出错样本比例。只有事先有依据的上限才能用于保证；留空就只做经验分析。"
      }),
      advanced
        ? (0, k.jsx)("p", {
            className: "inverse-note",
            children: "当前使用逐条预算或其他误差模型，请在上方 JSON 的 certification.noise 中编辑；此处不会改写它。"
          })
        : (0, k.jsxs)("label", {
            className: "inverse-editor-label",
            htmlFor: "inverse-noise-budget",
            children: [
              "每条历史允许的绝对费用误差（留空关闭保证）",
              (0, k.jsx)("input", {
                id: "inverse-noise-budget", type: "number", min: "0", step: "any",
                value: noise?.budget ?? "", disabled, placeholder: "需要独立依据，例如已知无误差才填 0",
                onChange: event => setBudget(event.target.value)
              })
            ]
          }),
      !!config && (0, k.jsxs)("label", {
        className: "inverse-editor-label",
        htmlFor: "inverse-risk-threshold",
        children: [
          "这个方案最多能接受多少额外费用（默认 0）",
          (0, k.jsx)("input", {
            id: "inverse-risk-threshold", type: "number", min: "0", step: "any",
            value: config.threshold ?? 0, disabled,
            onChange: event => setThreshold(event.target.value)
          })
        ]
      }),
      !!config && !advanced && !upperAdvanced && (0, k.jsxs)("label", {
        className: "inverse-editor-label",
        htmlFor: "inverse-noise-upper",
        children: [
          "额外检查：如果历史误差更大，上限是多少（可选）",
          (0, k.jsx)("input", {
            id: "inverse-noise-upper", type: "number", min: noise?.budget ?? 0, step: "any",
            value: upperNoise?.budget ?? "", disabled,
            placeholder: "留空不检查；必须有依据，且不小于原误差上限",
            onChange: event => setUpperBudget(event.target.value)
          })
        ]
      }),
      !!config && (advanced || upperAdvanced) && (0, k.jsx)("p", {
        className: "inverse-note",
        children: "逐条敏感性上限可在 JSON 的 certification.sensitivity.upperNoise.budgets 中声明；每条都必须不小于原预算。"
      }),
      upperNoise && !advanced && !upperAdvanced && upperNoise.budget < noise?.budget &&
        (0, k.jsx)("p", { className: "solver-stale",
          children: "额外检查的上限小于原预算，需要修正后运行；程序不会自动替你放大它。" }),
      !!config && (0, k.jsx)("p", {
        className: "inverse-note",
        children: "额外检查始终使用同一个方案。更大的上限仍是输入假设，不是程序发现的真实误差；两个端点也不能定位精确的风险转折点。两次检查分别使用计算预算，耗时会增加。"
      }),
      (0, k.jsx)("p", {
        className: "inverse-note",
        children: "勾选本地自动检查后运行。当前保证仅支持能完整枚举的小型有界整数问题。未提供 deployment 新场景时，只复查最后一条历史场景。证书采用协作式时间预算，实际耗时会包含精确核验开销；拟合与交叉验证另计。"
      })
    ]
  });
}

function inverseCertificationReport({ analysis }) {
  const value = analysis.compatibility;
  if (!value) return null;
  const certificate = value.decisionCertificate;
  const stale = analysis.supersededByModelProposal;
  const guidance = value.decisionGuidance;
  const sensitivity = value.noiseSensitivity;
  const guidanceStates = {
    conditional_safe: "在声明条件下满足损失阈值",
    risk_witness: "声明条件内已找到风险，不能给安全保证",
    incompatible: "假设与历史不相容，不能给安全保证",
    unresolved: "证据不足，暂不下安全结论"
  };
  const states = {
    complete: "相容集合与风险界已算完",
    partial: "计算尚未全部完成；已得到的外界仍可查看",
    incompatible: "当前假设与历史不相容",
    budget_required: "未声明误差上限，暂不提供决策保证",
    unsupported: "当前问题超出保证模块的支持范围"
  };
  const decisionStates = {
    safe: "在列明假设下，方案损失不超过阈值",
    risk_witness: "已找到超过阈值的相容反例",
    unresolved: "现有证据还不能下结论",
    incompatible: "假设与历史不相容，不能签发保证"
  };
  return (0, k.jsxs)("div", {
    className: "inverse-card inverse-certificate",
    children: [
      (0, k.jsx)("h2", { children: stale ? "原模型的决策保证（已过期）" : "在明确假设下检查决策" }),
      stale && (0, k.jsx)("p", {
        className: "solver-stale",
        children: "大模型已修改候选规则。以下证据只属于修改前的模型，不能用于保证当前规则产生的方案。"
      }),
      (0, k.jsx)("p", { children: states[value.status] || value.status }),
      value.note && (0, k.jsx)("p", { className: "inverse-note", children: value.note }),
      value.assumptionAudit && (0, k.jsx)("p", {
        className: "inverse-note", children: value.assumptionAudit.note
      }),
      guidance && (0, k.jsxs)("div", {
        className: "inverse-certificate-decision",
        children: [
          (0, k.jsx)("h3", {
            children: (stale ? "原模型综合结论（已过期）：" : "本次综合结论：") +
              (guidanceStates[guidance.status] || guidance.status)
          }),
          (0, k.jsx)("p", { children: guidance.note }),
          (0, k.jsx)("p", { className: "inverse-note",
            children: guidance.scope === "declared_upper_budget"
              ? "综合结论采用额外声明的较宽误差上限；上限本身仍未获独立验证。"
              : "只检查了原误差假设，尚未作跨预算保证。" })
        ]
      }),
      value.noiseModel && (0, k.jsx)("p", {
        className: "inverse-note",
        children: value.noiseModel.kind === "absolute"
          ? value.noiseModel.budgets
            ? "误差依据：输入中逐条声明的绝对费用上限。"
            : "误差依据：每条历史的绝对费用误差不超过 " + inverseCertificationNumber(value.noiseModel.budget) + "。"
          : "所声明的误差模型：" + value.noiseModel.kind
      }),
      (value.ranges || []).length > 0 && (0, k.jsxs)("details", {
        children: [
          (0, k.jsx)("summary", { children: "查看与误差上限相容的参数范围" }),
          (0, k.jsx)("p", {
            className: "inverse-note",
            children: "这些范围来自声明的误差上限。每个数字单独落在范围里，不代表它们拼起来也能解释历史；它们也不是统计置信区间。"
          }),
          value.ranges.map(range => (0, k.jsxs)("p", {
            children: [
              range.label || range.id, "：",
              inverseCertificationNumber(range.lower), " ～ ", inverseCertificationNumber(range.upper),
              range.status === "complete" ? "（已完成）" : "（保守外界，可能还会缩小）"
            ]
          }, range.id))
        ]
      }),
      certificate && (0, k.jsxs)("div", {
        className: "inverse-certificate-decision",
        children: [
          (0, k.jsx)("h3", {
            children: (stale ? "原模型单预算结果：" : "原误差预算下的结果：") + (decisionStates[certificate.status] || certificate.status)
          }),
          (0, k.jsx)("p", { children: certificate.note }),
          (0, k.jsxs)("p", {
            children: [
              "最坏额外费用：下界 ", inverseCertificationNumber(certificate.lowerBound),
              "；上界 ", inverseCertificationNumber(certificate.upperBound),
              "；接受阈值 ", inverseCertificationNumber(certificate.threshold), "。"
            ]
          }),
          value.deploymentSource && (0, k.jsx)("p", {
            className: "inverse-note",
            children: value.deploymentSource === "historical_context_replay"
              ? "检查对象：历史场景复查（" + value.deploymentId + "），不是新场景测试。"
              : "检查对象：输入中单独提供的场景（" + value.deploymentId + "）；它未作为历史加入相容条件。"
          }),
          certificate.chosenDecision && (0, k.jsxs)("details", {
            children: [
              (0, k.jsx)("summary", { children: "本次检查的具体方案" }),
              (0, k.jsx)("pre", { children: JSON.stringify(certificate.chosenDecision, null, 2) })
            ]
          })
        ]
      }),
      sensitivity && (0, k.jsxs)("details", {
        children: [
          (0, k.jsx)("summary", { children: "误差上限改变后，结论是否仍成立" }),
          (0, k.jsx)("p", { children: sensitivity.note }),
          sensitivity.upperNoise && (0, k.jsx)("p", {
            className: "inverse-note",
            children: sensitivity.upperNoise.budgets
              ? "额外上限：输入中逐条声明的预算。"
              : "额外上限：" + inverseCertificationNumber(sensitivity.upperNoise.budget)
          }),
          sensitivity.upperCertificate && (0, k.jsx)("p", {
            children: "上限处最坏额外费用：下界 " +
              inverseCertificationNumber(sensitivity.upperCertificate.lowerBound) +
              "；上界 " + inverseCertificationNumber(sensitivity.upperCertificate.upperBound) + "。"
          }),
          sensitivity.nominalStatus === "incompatible" && (0, k.jsx)("p", {
            className: "inverse-note",
            children: "原来较紧的预算仍与历史不相容；上限处的结果没有消除这条事实。"
          })
        ]
      }),
      (value.assumptions || []).length > 0 && (0, k.jsx)("p", {
        className: "inverse-note",
        children: "保证的前提：" + value.assumptions.join("；") + "。"
      })
    ]
  });
}

export { inverseCertificationInput, inverseCertificationReport };
