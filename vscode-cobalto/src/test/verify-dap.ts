// Headless verification of Cobalto's DAP proxy: it speaks DAP over stdio with
// out/dap-proxy.js (which in turn runs lldb-dap) and checks that the
// variables have COBOL names and that "next" lands on the next COBOL line.
//   node out/test/verify-dap.js <folder with cblt.json> [SUITE]
// First: cobalto debug --suite SUITE in that folder.

import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { DapMessage, DapReader, DapResponse, DapEvent, encode } from '../dap/protocol';
import { findLldbDap } from '../dap/find-lldb';

const project = path.resolve(process.argv[2] ?? '.');
const suite = (process.argv[3] ?? 'TSTINV').toUpperCase();
const lldb = findLldbDap([process.env.COBALTO_LLDB_DAP]);
if (!lldb) {
  console.error('lldb-dap was not found');
  process.exit(2);
}

const proxy = spawn(process.execPath, [path.join(__dirname, '..', 'dap-proxy.js'), '--lldb-dap', lldb, '--log'], { stdio: ['pipe', 'pipe', 'pipe'] });
proxy.stderr.on('data', (c: Buffer) => process.stderr.write(c.toString().split('\n').filter(Boolean).map((l) => '    ' + l + '\n').join('')));

let seq = 1;
const pending = new Map<number, (r: DapResponse) => void>();
const eventWaiters: { event: string; resolve: (e: DapEvent) => void }[] = [];
const events: DapEvent[] = [];
const reader = new DapReader((m: DapMessage) => {
  if (m.type === 'response') {
    const r = m as DapResponse;
    pending.get(r.request_seq)?.(r);
    pending.delete(r.request_seq);
  } else if (m.type === 'event') {
    const e = m as DapEvent;
    const i = eventWaiters.findIndex((w) => w.event === e.event);
    if (i >= 0) {
      const w = eventWaiters.splice(i, 1)[0];
      w.resolve(e);
    } else {
      events.push(e);
    }
  }
});
proxy.stdout.on('data', (c: Buffer) => reader.feed(c));

function request(command: string, args: Record<string, unknown> = {}): Promise<DapResponse> {
  const s = seq++;
  return new Promise((resolve) => {
    pending.set(s, resolve);
    proxy.stdin.write(encode({ seq: s, type: 'request', command, arguments: args }));
  });
}

function waitEvent(event: string, timeoutMs = 20000): Promise<DapEvent> {
  const i = events.findIndex((e) => e.event === event);
  if (i >= 0) {
    return Promise.resolve(events.splice(i, 1)[0]);
  }
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`timeout waiting for the ${event} event`)), timeoutMs);
    eventWaiters.push({ event, resolve: (e) => { clearTimeout(t); resolve(e); } });
  });
}

let failures = 0;
function check(cond: unknown, label: string): void {
  console.log(`  ${cond ? 'OK  ' : 'FAIL'} ${label}`);
  if (!cond) {
    failures++;
  }
}

interface Frame { id: number; name: string; line: number; source?: { path?: string; name?: string; presentationHint?: string }; presentationHint?: string }
interface Variable { name: string; value: string; type?: string; variablesReference: number; evaluateName?: string }

async function top(threadId: number): Promise<Frame> {
  const r = await request('stackTrace', { threadId, startFrame: 0, levels: 20 });
  const frames = (r.body?.stackFrames as Frame[]) ?? [];
  console.log('  stack: ' + frames.slice(0, 4).map((f) => `${f.name}@${f.source?.name ?? '?'}:${f.line}${f.presentationHint === 'subtle' ? '(subtle)' : ''}`).join(' > '));
  return frames[0];
}

async function variablesOf(frameId: number, scopeName: string): Promise<Variable[]> {
  const sc = await request('scopes', { frameId });
  const scope = ((sc.body?.scopes as { name: string; variablesReference: number }[]) ?? []).find((s) => s.name === scopeName);
  if (!scope) {
    return [];
  }
  const v = await request('variables', { variablesReference: scope.variablesReference });
  return (v.body?.variables as Variable[]) ?? [];
}

function firstLineMatching(file: string, re: RegExp, from = 1): number {
  const lines = fs.readFileSync(file, 'utf8').split('\n');
  for (let i = from - 1; i < lines.length; i++) {
    if (re.test(lines[i])) {
      return i + 1;
    }
  }
  throw new Error(`${re} was not found in ${file}`);
}

async function main(): Promise<void> {
  const genCbl = path.join(project, 'build', `${suite}.cbl`);
  const discount = path.join(project, 'src', 'DISCOUNT.cbl');
  const cblt = path.join(project, 'tests', 'INVOICE.cblt');
  const performLine = firstLineMatching(genCbl, /^\s{7,}PERFORM 2100-CALC/);
  const cbltPerformLine = fs.existsSync(cblt) ? firstLineMatching(cblt, /^\s{7,}PERFORM 2100-CALC/) : 0;
  const cbltMoveLine = fs.existsSync(cblt) ? firstLineMatching(cblt, /^\s{7,}MOVE 2000 TO WS-C-AMOUNT/) : 0;
  const computeLine = firstLineMatching(discount, /COMPUTE LN-RESULT/);
  console.log(`project ${project}, suite ${suite}, lldb-dap ${lldb}`);
  console.log(`breakpoints: ${path.relative(project, genCbl)}:${performLine}, DISCOUNT.cbl:${computeLine}${cbltPerformLine ? `, INVOICE.cblt:${cbltPerformLine}` : ''}`);

  const init = await request('initialize', { clientID: 'cobalto-verify', adapterID: 'cobalto', linesStartAt1: true, columnsStartAt1: true, pathFormat: 'path', supportsVariableType: true });
  check(init.success, 'initialize');
  const launchP = request('launch', { program: path.join(project, 'build', 'cbltdrv'), cwd: project, suite, stopOnEntry: false });
  await waitEvent('initialized');
  const bp1 = await request('setBreakpoints', { source: { name: path.basename(genCbl), path: genCbl }, breakpoints: [{ line: performLine }] });
  const b1 = (bp1.body?.breakpoints as { verified: boolean; line: number }[]) ?? [];
  check(b1[0]?.verified, `breakpoint at ${path.basename(genCbl)}:${performLine} verified (${JSON.stringify(b1[0])})`);
  const bp2 = await request('setBreakpoints', { source: { name: 'DISCOUNT.cbl', path: discount }, breakpoints: [{ line: computeLine, condition: 'LN-AMOUNT >= 2000 AND NOT LN-AMOUNT > 2000' }] });
  const b2 = (bp2.body?.breakpoints as { verified: boolean }[]) ?? [];
  check(b2[0]?.verified, `breakpoint at DISCOUNT.cbl:${computeLine} verified (${JSON.stringify(b2[0])})`);
  if (cbltPerformLine) {
    const bp3 = await request('setBreakpoints', { source: { name: 'INVOICE.cblt', path: cblt }, breakpoints: [{ line: cbltPerformLine }] });
    const b3 = (bp3.body?.breakpoints as { verified: boolean }[]) ?? [];
    check(b3[0]?.verified, `breakpoint at INVOICE.cblt:${cbltPerformLine} moved and verified (${JSON.stringify(b3[0])})`);
    // we replace it with one on the previous MOVE with a false COBOL condition
    // (WS-C-AMOUNT is still 0): the stop has to be the one at the PERFORM
    const bp4 = await request('setBreakpoints', { source: { name: 'INVOICE.cblt', path: cblt }, breakpoints: [{ line: cbltMoveLine, condition: 'WS-C-AMOUNT = 2000' }] });
    const b4 = (bp4.body?.breakpoints as { verified: boolean }[]) ?? [];
    check(b4[0]?.verified, `conditional breakpoint at INVOICE.cblt:${cbltMoveLine} (WS-C-AMOUNT = 2000) verified`);
  }
  await request('configurationDone');
  const launch = await launchP;
  check(launch.success, `launch (${launch.message ?? 'ok'})`);

  let stopped = await waitEvent('stopped');
  let threadId = (stopped.body as { threadId: number }).threadId;
  console.log(`stop 1: ${JSON.stringify(stopped.body)}`);
  let frame = await top(threadId);
  const shownFile = frame.source?.path ?? '';
  check(/\.(cbl|cblt)$/i.test(shownFile), `top frame in a COBOL source (${path.basename(shownFile)}:${frame.line})`);
  const expectedOrigin = cbltPerformLine ? { file: 'INVOICE.cblt', line: cbltPerformLine } : { file: path.basename(genCbl), line: performLine };
  check(path.basename(shownFile) === expectedOrigin.file && frame.line === expectedOrigin.line, `frame mapped to the origin ${expectedOrigin.file}:${expectedOrigin.line}`);
  if (cbltMoveLine) {
    check(frame.line !== cbltMoveLine, `the false condition at INVOICE.cblt:${cbltMoveLine} did not stop (stopped at line ${frame.line})`);
  }

  const globals = await variablesOf(frame.id, 'Globals');
  const names = globals.map((v) => v.name);
  const wsAmount = globals.find((v) => v.name === 'WS-AMOUNT');
  check(wsAmount !== undefined, `Globals shows WS-AMOUNT (${wsAmount ? `value ${wsAmount.value}, type ${wsAmount.type}` : 'missing; names: ' + names.slice(0, 8).join(', ')})`);
  check(!names.some((n) => /^b_\d+$/.test(n)), `no untranslated b_NNN in Globals (${names.length} entries: ${names.slice(-3).join(', ')})`);
  const internals = globals.find((v) => v.name === '(GnuCOBOL internals)');
  check(internals !== undefined && internals.variablesReference > 0, `GnuCOBOL internals grouped (${internals?.value})`);
  const wsCust = globals.find((v) => v.name === 'WS-CUST');
  check(wsCust !== undefined && wsCust.variablesReference > 0, `WS-CUST is an expandable group (${wsCust ? wsCust.variablesReference : 'missing'})`);
  if (wsCust && wsCust.variablesReference > 0) {
    const kids = (await request('variables', { variablesReference: wsCust.variablesReference })).body?.variables as Variable[];
    console.log('  children of WS-CUST: ' + kids.map((k) => `${k.name}=${k.value}`).join(', '));
    check(kids.some((k) => k.name === 'WS-C-AMOUNT'), 'WS-C-AMOUNT appears as a child of WS-CUST');
    check(kids.filter((k) => /^WS-C-/.test(k.name)).length === 3 && kids.some((k) => /offset 4\b/.test(k.type ?? '')), `the three subfields of WS-CUST with their offset (${kids.map((k) => k.type).join(' | ')})`);
    // setVariable on a subfield (layout + writeMemory) and back to the original value
    const sv = await request('setVariable', { variablesReference: wsCust.variablesReference, name: 'WS-C-AMOUNT', value: '1234.5' });
    check(sv.success && /^0001234\.50$/.test(String(sv.body?.value)), `setVariable WS-C-AMOUNT = 1234.5 -> ${sv.body?.value ?? sv.message}`);
    const after = await request('evaluate', { expression: 'WS-C-AMOUNT', frameId: frame.id, context: 'watch' });
    check(/^0001234\.50$/.test(String(after.body?.result)), `evaluate after setVariable = ${after.body?.result}`);
    await request('setVariable', { variablesReference: wsCust.variablesReference, name: 'WS-C-AMOUNT', value: '2000' });
  }
  // setVariable on an alphanumeric 01 from the scope and back to spaces
  const sc = await request('scopes', { frameId: frame.id });
  const globalsRef = ((sc.body?.scopes as { name: string; variablesReference: number }[]) ?? []).find((s) => s.name === 'Globals')?.variablesReference ?? 0;
  const svc = await request('setVariable', { variablesReference: globalsRef, name: 'WS-CATEGORY', value: 'TEST' });
  check(svc.success && String(svc.body?.value) === '"TEST      "', `setVariable WS-CATEGORY = TEST -> ${svc.body?.value ?? svc.message}`);
  await request('setVariable', { variablesReference: globalsRef, name: 'WS-CATEGORY', value: '' });
  // OCCURS: subscripts in the console (CBLT-MODE OCCURS 5 in the suite, CBLT-LOG OCCURS 500 in the LINKAGE context)
  const occ = await request('evaluate', { expression: 'CBLT-MODE(2)', frameId: frame.id, context: 'repl' });
  check(occ.success && /^\d{3}$/.test(String(occ.body?.result)), `evaluate CBLT-MODE(2) = ${occ.body?.result ?? occ.message}`);
  const occBad = await request('evaluate', { expression: 'CBLT-MODE(6)', frameId: frame.id, context: 'repl' });
  check(!occBad.success && /out of range 1\.\.5/.test(String(occBad.message)), `evaluate CBLT-MODE(6) rejected (${occBad.message})`);
  const lnk = await request('evaluate', { expression: 'CBLT-LOG-NR(1)', frameId: frame.id, context: 'repl' });
  check(lnk.success && /^\d{5}$/.test(String(lnk.body?.result)), `evaluate CBLT-LOG-NR(1) (OCCURS in LINKAGE) = ${lnk.body?.result ?? lnk.message}`);
  const grp = await request('evaluate', { expression: 'WS-CUST', frameId: frame.id, context: 'watch' });
  check(grp.success && Number(grp.body?.variablesReference) > 0, `evaluate WS-CUST returns an expandable group (${grp.body?.variablesReference})`);
  console.log('  Globals: ' + globals.slice(0, 12).map((v) => `${v.name}=${v.value}`).join(', '));
  const ev = await request('evaluate', { expression: 'WS-C-AMOUNT', frameId: frame.id, context: 'hover' });
  check(ev.success && /2000/.test(String(ev.body?.result)), `evaluate WS-C-AMOUNT = ${ev.body?.result ?? ev.message}`);

  // next: it has to land on the next COBOL line, not in the .c
  const beforeLine = frame.line;
  const beforeFile = path.basename(shownFile);
  await request('next', { threadId });
  stopped = await waitEvent('stopped');
  check((stopped.body as { reason: string }).reason === 'step', `next: stopped by step (${JSON.stringify(stopped.body)})`);
  frame = await top(threadId);
  const afterFile = frame.source?.path ?? '';
  check(/\.(cbl|cblt)$/i.test(afterFile), `next lands in a COBOL source (${path.basename(afterFile)}:${frame.line})`);
  check(!(path.basename(afterFile) === beforeFile && frame.line === beforeLine), `next moved from ${beforeFile}:${beforeLine} to ${path.basename(afterFile)}:${frame.line}`);
  // second next, from the PERFORM line it goes through the C and through paragraph 2100-CALC
  await request('next', { threadId });
  await waitEvent('stopped');
  frame = await top(threadId);
  check(/\.(cbl|cblt)$/i.test(frame.source?.path ?? ''), `second next lands in COBOL (${frame.source?.name}:${frame.line})`);

  // continue to DISCOUNT.cbl
  await request('continue', { threadId });
  stopped = await waitEvent('stopped');
  threadId = (stopped.body as { threadId: number }).threadId;
  console.log(`stop 2: ${JSON.stringify(stopped.body)}`);
  frame = await top(threadId);
  check(path.basename(frame.source?.path ?? '') === 'DISCOUNT.cbl' && frame.line === computeLine, `stopped at DISCOUNT.cbl:${computeLine} with a true COBOL condition (${frame.source?.name}:${frame.line})`);
  const locals = await variablesOf(frame.id, 'Locals');
  console.log('  Locals: ' + locals.map((v) => `${v.name}=${v.value}`).join(', '));
  check(locals.some((v) => v.name === 'LN-AMOUNT'), 'Locals shows LN-AMOUNT (LINKAGE parameter)');
  check(locals.some((v) => v.name === 'LN-CATEGORY'), 'Locals shows LN-CATEGORY (parameter without a descriptor, name taken from the .c)');
  check(locals.some((v) => v.name === 'LN-RESULT' && /^"?\d+\.\d+"?$/.test(v.value)), `LN-RESULT formatted even though the descriptor has no data (${locals.find((v) => v.name === 'LN-RESULT')?.value})`);
  check(locals.some((v) => v.name === 'LN-CATEGORY' && /^"/.test(v.value)), `LN-CATEGORY with a text value from the layout (${locals.find((v) => v.name === 'LN-CATEGORY')?.value})`);
  const dg = await variablesOf(frame.id, 'Globals');
  const rate = dg.find((v) => v.name === 'WS-RATE');
  check(rate !== undefined, `Globals of DISCOUNT shows WS-RATE (${rate?.value})`);
  const ev2 = await request('evaluate', { expression: 'ln-amount', frameId: frame.id, context: 'repl' });
  check(ev2.success, `evaluate ln-amount from the console = ${ev2.body?.result ?? ev2.message}`);
  await request('next', { threadId });
  await waitEvent('stopped');
  frame = await top(threadId);
  check(path.basename(frame.source?.path ?? '') === 'DISCOUNT.cbl' && frame.line === computeLine + 1, `next in DISCOUNT goes to line ${computeLine + 1} (${frame.source?.name}:${frame.line})`);
  // stepOut returns to the caller on a COBOL line
  await request('stepOut', { threadId });
  await waitEvent('stopped');
  frame = await top(threadId);
  check(/\.(cbl|cblt)$/i.test(frame.source?.path ?? ''), `stepOut returns to a COBOL line (${frame.source?.name}:${frame.line})`);

  await request('setBreakpoints', { source: { name: 'DISCOUNT.cbl', path: discount }, breakpoints: [] });
  await request('setBreakpoints', { source: { name: path.basename(genCbl), path: genCbl }, breakpoints: [] });
  await request('continue', { threadId });
  const ended = await Promise.race([waitEvent('terminated', 30000), waitEvent('exited', 30000)]);
  check(!!ended, `the program ended (${ended.event})`);
  await request('disconnect', {});
  proxy.stdin.end();
  console.log(failures ? `\n${failures} checks failed` : '\nall verified');
  process.exit(failures ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  proxy.kill();
  process.exit(1);
});
