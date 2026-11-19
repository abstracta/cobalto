// Reader for build/cov/map.json: the label (THEN, ELSE, WHEN ..., operand
// true/false) and the own line of each branch, by file and by
// "statement index:ordinal", which is how BRDA numbers them in lcov.info.
// No dependency on VS Code.

import { schemaProblem } from './dap/schema';

export interface BranchInfo {
  label: string;
  line: number;
}

/** file (as it appears in SF) -> "statement index:ordinal" -> branch */
export type BranchLabels = Map<string, Map<string, BranchInfo>>;

interface ProgramMap {
  branches?: { stmt: number; label: string; line: number; file: string }[];
}

/**
 * The branches of a parsed map.json. Since the "schema" field exists, the
 * programs are under "programs"; before it, they were the top level. A map
 * with a newer schema is not used: `problem` says why.
 */
export function branchLabelsFrom(data: unknown, file: string): { labels: BranchLabels; problem?: string } {
  const labels: BranchLabels = new Map();
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return { labels };
  }
  const doc = data as { schema?: unknown; cobalto?: unknown; programs?: unknown };
  const problem = schemaProblem(doc, file);
  if (problem) {
    return { labels, problem };
  }
  const programs = typeof doc.schema === 'number' ? doc.programs : data;
  if (typeof programs !== 'object' || programs === null) {
    return { labels };
  }
  for (const m of Object.values(programs as Record<string, ProgramMap | null>)) {
    const ordinal = new Map<number, number>();
    for (const b of m?.branches ?? []) {
      const i = ordinal.get(b.stmt) ?? 0;
      ordinal.set(b.stmt, i + 1);
      let byFile = labels.get(b.file);
      if (!byFile) {
        byFile = new Map();
        labels.set(b.file, byFile);
      }
      byFile.set(`${b.stmt}:${i}`, { label: b.label, line: b.line });
    }
  }
  return { labels };
}
