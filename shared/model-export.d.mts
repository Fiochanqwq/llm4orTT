import type { LinearModel } from './solver-model.mjs';
export type ModelFormat = 'json' | 'lp' | 'py' | 'tex';
export function modelLP(model: LinearModel): string;
export function exportModel(model: LinearModel, format: ModelFormat, engine?: string, seconds?: number): { text: string; name: string; type: string };
