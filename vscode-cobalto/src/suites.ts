// A project's suites and test cases, as the CLI reads them (cobalto list
// --json): .cblt files (DSL) and COBOL tests without the DSL. The extension
// does not parse the DSL itself. No dependency on VS Code.

import * as path from 'path';

export interface SuiteCase {
  name: string;
  line: number;
  ignored: boolean;
}

export interface SuiteInfo {
  id: string;
  description: string;
  /** absolute path */
  file: string;
  line: number;
  program?: string;
  cases: SuiteCase[];
  /** a COBOL test without the DSL: it runs as a single test case */
  legacy: boolean;
}

/** A suite file the CLI could not read (a syntax error of the DSL). */
export interface SuiteError {
  file: string;
  line: number;
  message: string;
}

export interface SuiteListing {
  suites: SuiteInfo[];
  errors: SuiteError[];
  /** false when the CLI did not answer (not installed, or an older one) */
  ok: boolean;
}

interface ListDocument {
  suites?: { id: string; file: string; line: number; description?: string; dsl: boolean; program?: string | null; cases?: SuiteCase[] }[];
  errors?: { file: string; line: number | string; code: string; message: string }[];
}

/** The document of cobalto list --json as the extension uses it. */
export function listingFrom(doc: unknown, root: string): SuiteListing {
  const d = doc as ListDocument | undefined;
  if (!d || !Array.isArray(d.suites)) {
    return { suites: [], errors: [], ok: false };
  }
  return {
    ok: true,
    suites: d.suites.map((s) => ({
      id: s.id,
      description: s.dsl ? s.description ?? '' : 'COBOL test without the DSL',
      file: path.resolve(root, s.file),
      line: s.line,
      program: s.program ?? undefined,
      cases: s.cases ?? [],
      legacy: !s.dsl,
    })),
    errors: (d.errors ?? []).map((e) => ({
      file: path.resolve(root, e.file),
      line: typeof e.line === 'number' ? e.line : 1,
      message: `${e.code}: ${e.message}`,
    })),
  };
}
