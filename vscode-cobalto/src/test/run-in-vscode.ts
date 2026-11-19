// Launches the installed VS Code with the extension in development mode and runs
// src/test/suite inside the extension host (actual verification in VS Code).
//   node out/test/run-in-vscode.js <folder with cblt.json>

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { runTests } from '@vscode/test-electron';

async function main(): Promise<void> {
  const extensionDevelopmentPath = path.resolve(__dirname, '..', '..');
  const extensionTestsPath = path.resolve(__dirname, 'suite', 'index.js');
  const project = path.resolve(process.argv[2] ?? path.join(extensionDevelopmentPath, '..', 'examples'));
  const candidates = [
    process.env.COBALTO_VSCODE,
    '/Applications/Visual Studio Code.app/Contents/MacOS/Code', '/Applications/Visual Studio Code.app/Contents/MacOS/Electron',
  ].filter((c): c is string => !!c && fs.existsSync(c));
  const code = await runTests({
    vscodeExecutablePath: candidates[0],
    extensionDevelopmentPath,
    extensionTestsPath,
    // its own user-data-dir: otherwise the binary hands it over to the VS Code instance already open
    launchArgs: [project, `--user-data-dir=${path.join(os.tmpdir(), 'cobalto-vscode-verify')}`, '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes', '--disable-gpu'],
    extensionTestsEnv: { COBALTO_TEST_PROJECT: project },
  });
  process.exit(code);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
