// stdio entry point of Cobalto's DAP proxy. Used by the extension in
// "process" mode and by the headless verification script.
//   node out/dap-proxy.js [--lldb-dap PATH] [--log] [--trace] [--no-format]

import { CobaltoDapProxy } from './dap/proxy';
import { DapReader, encode } from './dap/protocol';
import { findLldbDap } from './dap/find-lldb';

function main(): void {
  const argv = process.argv.slice(2);
  let lldb: string | undefined;
  let log = false;
  let trace = false;
  let formatValues = true;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--lldb-dap') {
      lldb = argv[++i];
    } else if (argv[i] === '--log') {
      log = true;
    } else if (argv[i] === '--trace') {
      log = true;
      trace = true;
    } else if (argv[i] === '--no-format') {
      formatValues = false;
    }
  }
  const lldbPath = findLldbDap([lldb, process.env.COBALTO_LLDB_DAP]);
  if (!lldbPath) {
    process.stderr.write('Cobalto: lldb-dap was not found (use --lldb-dap PATH or the COBALTO_LLDB_DAP variable)\n');
    process.exit(2);
  }
  const proxy = new CobaltoDapProxy((m) => process.stdout.write(encode(m)), {
    lldbDapPath: lldbPath,
    log: log || process.env.COBALTO_DAP_LOG ? (s) => process.stderr.write(`[cobalto-dap] ${s}\n`) : undefined,
    trace: trace || process.env.COBALTO_DAP_LOG === 'trace',
    formatValues,
  });
  const reader = new DapReader((m) => proxy.handleClientMessage(m));
  process.stdin.on('data', (c: Buffer) => reader.feed(c));
  process.stdin.on('end', () => {
    proxy.dispose();
    process.exit(0);
  });
}

main();
