export const methodPresets: Record<string,{label:string;structured:boolean;semantic:boolean;budget:boolean;repair:boolean;delivery:boolean;programmatic?:boolean}>;
export const methodVersion: string;
export const interactiveMethodIds: readonly string[];
export function methodLabel(id:string,language?:string):string;
