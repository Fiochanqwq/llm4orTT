export type LinearModel = { format: string; name: string; sense: string; variables: { name: string; type: string; lower: number | null; upper: number | null }[]; objective: Record<string, number>; constraints: { name: string; terms: Record<string, number>; sense: string; rhs: number }[] };
export const demoModel: LinearModel;
export const demoProblem: Record<'zh-CN' | 'en', string>;
export function validateModel(input: unknown): LinearModel;
export function pyomoSource(input: unknown, engine?: string, seconds?: number): string;
export function modelingPrompt(problem: string, language?: 'zh-CN' | 'en'): string;
