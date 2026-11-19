// Reader for build/lcov.info (DA per statement, FN/FNDA per paragraph, BRDA per branch).

export interface LcovFile {
  /** path as it appears in SF (relative to the project) */
  path: string;
  lines: Map<number, number>;
  functions: { name: string; line: number; hits: number }[];
  /** BRDA: line of the statement, index of the statement in the map, ordinal of the branch and hits */
  branches: { line: number; stmt: number; ordinal: number; taken: number }[];
}

export function parseLcov(text: string): LcovFile[] {
  const out: LcovFile[] = [];
  let cur: LcovFile | undefined;
  const fnLines = new Map<string, number>();
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (line.startsWith('SF:')) {
      cur = { path: line.slice(3), lines: new Map(), functions: [], branches: [] };
      fnLines.clear();
    } else if (!cur) {
      continue;
    } else if (line.startsWith('DA:')) {
      const [l, h] = line.slice(3).split(',');
      cur.lines.set(parseInt(l, 10), parseInt(h, 10));
    } else if (line.startsWith('BRDA:')) {
      const [l, stmt, ordinal, taken] = line.slice(5).split(',');
      cur.branches.push({ line: parseInt(l, 10), stmt: parseInt(stmt, 10), ordinal: parseInt(ordinal, 10), taken: taken === '-' ? 0 : parseInt(taken, 10) });
    } else if (line.startsWith('FN:')) {
      const [l, name] = line.slice(3).split(',');
      fnLines.set(name, parseInt(l, 10));
      cur.functions.push({ name, line: parseInt(l, 10), hits: 0 });
    } else if (line.startsWith('FNDA:')) {
      const [h, name] = line.slice(5).split(',');
      const fn = cur.functions.find((f) => f.name === name);
      if (fn) {
        fn.hits = parseInt(h, 10);
      }
    } else if (line === 'end_of_record') {
      out.push(cur);
      cur = undefined;
    }
  }
  if (cur) {
    out.push(cur);
  }
  return out;
}
