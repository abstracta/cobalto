// Where the cobalto executable is. No dependency on VS Code, so that it can
// be checked from plain Node.

import * as fs from 'fs';
import * as path from 'path';

/**
 * The cobalto executable for a project, in this order: the path given in
 * the settings (relative paths start at the project folder), a virtual
 * environment (.venv) in the project folder or in one above it, and the PATH.
 */
export function resolveCli(projectRoot: string, custom: string, platform: string = process.platform): string {
  if (custom) {
    return path.resolve(projectRoot, custom);
  }
  const inVenv = platform === 'win32' ? path.join('.venv', 'Scripts', 'cobalto.exe') : path.join('.venv', 'bin', 'cobalto');
  for (let dir = projectRoot; ; dir = path.dirname(dir)) {
    const candidate = path.join(dir, inVenv);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
    if (path.dirname(dir) === dir) {
      return 'cobalto';
    }
  }
}
