type Node = { type: string; value?: string; children?: Node[]; data?: unknown };
// Work on parsed prose only: links, code, and existing math stay untouched.
export function remarkMathVariables() {
  return (tree: Node) => {
    const math = (raw: string): Node => {
      const value = raw.replace(/_([A-Za-z0-9]+)$/, '_{$1}');
      return { type: 'inlineMath', value, data: { hName: 'code', hProperties: { className: ['language-math', 'math-inline'] }, hChildren: [{ type: 'text', value }] } };
    };
    function visit(node: Node) {
      if (!node.children || ['link', 'linkReference', 'code', 'inlineCode', 'math', 'inlineMath'].includes(node.type)) return;
      node.children = node.children.flatMap(child => {
        if (child.type === 'inlineCode' && /^[A-Za-z]_[A-Za-z0-9]+$/.test(child.value || '')) return [math(child.value!)];
        if (child.type !== 'text' || !child.value) { visit(child); return [child]; }
        const result: Node[] = []; let last = 0;
        const pattern = /(?<![A-Za-z0-9_./\\])[A-Za-z]_(?:\{[A-Za-z0-9]+(?:\s*,\s*[A-Za-z0-9]+)*\}|[A-Za-z0-9]+)(?![A-Za-z0-9_]|\.[A-Za-z])/g;
        for (const match of child.value.matchAll(pattern)) {
          result.push({ type: 'text', value: child.value.slice(last, match.index) }, math(match[0]));
          last = match.index! + match[0].length;
        }
        result.push({ type: 'text', value: child.value.slice(last) }); return result;
      });
    }
    visit(tree);
  };
}
