export const methodPresets: Record<string,{label:string;structured:boolean;semantic:boolean;budget:boolean;repair:boolean;delivery:boolean}>;
export const methodVersion: string;
export function methodLabel(id:string,language?:string):string;
