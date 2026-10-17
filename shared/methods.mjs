// Adaptations of research ideas, not reproductions of the authors' full systems.
export const methodPresets = Object.freeze({
  generic: { label: 'Generic · same solver', structured: false, semantic: false, budget: false, repair: false, delivery: true },
  legacy: { label: 'Legacy compatibility', structured: false, semantic: false, budget: false, repair: false, delivery: false },
  delivery: { label: 'Delivery only', structured: false, semantic: false, budget: false, repair: false, delivery: true },
  structure: { label: 'S0 Q0', structured: true, semantic: false, budget: false, repair: false, delivery: true },
  semantic: { label: 'S1 Q0', structured: true, semantic: true, budget: false, repair: true, delivery: true },
  budget: { label: 'S0 Q1', structured: true, semantic: false, budget: true, repair: false, delivery: true },
  audit: { label: 'Audit without repair', structured: true, semantic: true, budget: true, repair: false, delivery: true },
  full: { label: 'S1 Q1 · full', structured: true, semantic: true, budget: true, repair: true, delivery: true }
});
export const methodVersion = '0.7.7-assistant-1';
export function methodLabel(id,language='zh-CN'){return language==='en'?methodPresets[id]?.label||id:({legacy:'历史兼容路径',delivery:'仅交付修复',generic:'通用同工具基线',structure:'S0 Q0 · 结构基础',semantic:'S1 Q0 · 语义审核',budget:'S0 Q1 · 预算判定',audit:'审核但不修复',full:'S1 Q1 · 完整方法'})[id]||id;}
export const paperRefs = { modeling: ['https://arxiv.org/abs/2602.15983'], semantic: ['https://arxiv.org/abs/2510.05115'], budget: ['https://arxiv.org/abs/2609.05258'] };
export function frozenConfig(config, engine, preset) {
  return { provider: config.id, model: config.model, baseURL: config.baseURL || '', region: config.region, maxTokens: config.maxTokens,
    modelingTokens: config.modelingTokens, engine, language: config.language, preset, methodVersion,
    protocolVersion: 'llm4orovo.submission.v4', protocolCorrection: config.protocolCorrection !== false,
    modelSeed: null, temperature: null };
}
