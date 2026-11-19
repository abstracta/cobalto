import { execFileSync } from 'child_process';
import * as fs from 'fs';

/** Finds lldb-dap: explicit candidates, then xcrun (macOS), then the PATH. */
export function findLldbDap(candidates: (string | undefined)[] = []): string | undefined {
  for (const c of candidates) {
    if (c && fs.existsSync(c)) {
      return c;
    }
  }
  if (process.platform === 'darwin') {
    try {
      const p = execFileSync('xcrun', ['-f', 'lldb-dap'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
      if (p && fs.existsSync(p)) {
        return p;
      }
    } catch {
      /* no xcrun */
    }
  }
  for (const name of ['lldb-dap', 'lldb-dap-20', 'lldb-dap-19', 'lldb-dap-18']) {
    try {
      const cmd = process.platform === 'win32' ? 'where' : 'which';
      const p = execFileSync(cmd, [name], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).split(/\r?\n/)[0].trim();
      if (p && fs.existsSync(p)) {
        return p;
      }
    } catch {
      /* next one */
    }
  }
  return undefined;
}
