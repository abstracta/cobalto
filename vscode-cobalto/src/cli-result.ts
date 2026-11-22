// Reading how a run of the CLI ended. No dependency on VS Code.

/**
 * Whether `cobalto test` got to write its results. Exit 0 means every test
 * case passed and 1 that some failed; anything else (2 for an error of the
 * CLI, null when the process was killed) means it stopped before running the
 * suites, and build/ holds no results of this run: since CLI 0.8.0 its
 * reports carry the error, and before, or when cblt.json cannot be read, they
 * belong to an earlier run.
 */
export function wroteResults(code: number | null): boolean {
  return code === 0 || code === 1;
}

/** Why the CLI stopped: its CBLT-Exxx lines, or the end of what it wrote. */
export function stopReason(output: string): string {
  const lines = output.split(/\r?\n/).filter((l) => l.trim());
  const errors = lines.filter((l) => /\bCBLT-E\d+/.test(l));
  return (errors.length ? errors : lines.slice(-5)).join('\n');
}
