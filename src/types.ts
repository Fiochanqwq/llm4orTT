export type Provider = { id: string; name: string; defaultModel: string; models: string[]; regions: { id: string; name: string; baseURL: string; models?: string[] }[] };
export type ProviderSettings = { region: string; model: string; baseURL: string; maxTokens: number; hasKey: boolean; models: string[] };
export type Workspace = { version: number; preferences: { provider: string; theme: 'light' | 'graphite'; fontSize: number }; providers: Record<string, ProviderSettings>; catalog: Provider[] };
export type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string; status: string; createdAt: string; model?: string; error?: string; warning?: string };
export type Conversation = { id: string; title: string; createdAt: string; updatedAt: string; messages: ChatMessage[] };
