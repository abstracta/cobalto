// Verification inside VS Code: Test Explorer, coverage and an actual
// debug session with the "cobalto" type (provider, cobalto debug, inline
// adapter, COBOL names and step per statement).

import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { readProfiles } from '../../profile';
import { projectFor } from '../../project';
import type { CobaltoApi } from '../../extension';

const project = process.env.COBALTO_TEST_PROJECT ?? '';
let failures = 0;
const lines: string[] = [];

function log(s: string): void {
  lines.push(s);
  console.log(s);
}

function check(cond: unknown, label: string): void {
  log(`  ${cond ? 'OK  ' : 'FAIL'} ${label}`);
  if (!cond) {
    failures++;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitFor<T>(label: string, fn: () => T | undefined | Promise<T | undefined>, timeoutMs: number): Promise<T | undefined> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const v = await fn();
    if (v !== undefined && v !== false) {
      return v;
    }
    await sleep(250);
  }
  log(`  (timeout waiting for ${label})`);
  return undefined;
}

function firstLineMatching(file: string, re: RegExp): number {
  const ls = fs.readFileSync(file, 'utf8').split('\n');
  const i = ls.findIndex((l) => re.test(l));
  if (i < 0) {
    throw new Error(`${re} was not found in ${file}`);
  }
  return i + 1;
}

interface Frame { id: number; name: string; line: number; source?: { path?: string; name?: string }; presentationHint?: string }

export async function run(): Promise<void> {
  log(`project: ${project}`);
  const ext = vscode.extensions.getExtension<CobaltoApi>('abstracta.vscode-cobalto');
  check(ext !== undefined, 'extension abstracta.vscode-cobalto present');
  const api = await ext!.activate();
  check(ext!.isActive, 'extension active');
  const bitlang = vscode.extensions.getExtension('bitlang.cobol');
  if (bitlang) {
    await waitFor('bitlang.cobol', () => bitlang.isActive || undefined, 15000);
    check(bitlang.isActive, 'bitlang.cobol still active (no COBOL debugger conflict)');
  } else {
    log('  (bitlang.cobol not installed in this instance)');
  }

  // --- Test Explorer
  await api.tests.discover();
  const items: vscode.TestItem[] = [];
  const walk = (c: vscode.TestItemCollection) => c.forEach((i) => { items.push(i); walk(i.children); });
  walk(api.tests.controller.items);
  const tstdisc = items.find((i) => i.label === 'TSTDISC');
  check(tstdisc !== undefined && tstdisc.children.size === 4, `suite TSTDISC with 4 test cases in the Test Explorer (${tstdisc?.children.size})`);
  const suites = [...api.tests.controller.items].map(([, i]) => i.label);
  check(suites.includes('TSTCATEG'), `legacy test TSTCATEG listed (suites: ${suites.join(', ')})`);
  const ignored = items.find((i) => i.label.startsWith('pending: negative amounts'));
  check(ignored?.description === 'IGNORE', 'IGNORE test case marked');
  const pendLine = firstLineMatching(path.join(project, 'tests', 'DISCOUNT.cblt'), /TESTCASE 'pending/);
  check(ignored?.uri?.fsPath.endsWith('DISCOUNT.cblt') && ignored?.range?.start.line === pendLine - 1, `test case located at DISCOUNT.cblt:${(ignored?.range?.start.line ?? -1) + 1}`);
  await api.tests.runAll();
  await api.tests.whenIdle();
  const r = api.tests.lastResults;
  const state = (label: string) => { const it = items.find((i) => i.label === label); return it ? r.get(it.id) : undefined; };
  check(state('premium amount gets 20%') === 'passed', `passing test case: ${state('premium amount gets 20%')}`);
  check(state('intentional failure to show the report') === 'failed', `intentional failure: ${state('intentional failure to show the report')}`);
  check(state('pending: negative amounts') === 'skipped', `IGNORE test case: ${state('pending: negative amounts')}`);
  check(state('TSTCATEG') === 'passed', `legacy test: ${state('TSTCATEG')}`);
  const counts = { passed: 0, failed: 0, skipped: 0, errored: 0 } as Record<string, number>;
  for (const v of r.values()) {
    counts[v] = (counts[v] ?? 0) + 1;
  }
  check(counts.failed === 2 && counts.skipped === 6 && counts.errored === 0 && counts.passed + 8 === 105, `105 test cases: ${JSON.stringify(counts)}`);
  check(state('interface: master file goes in, transactions come out') === 'passed', `TSTBATCH interface test case: ${state('interface: master file goes in, transactions come out')}`);
  // suites for programs that model a business: TSTCLOSE, TSTLOAN, TSTBATCH
  const tstclose = items.find((i) => i.label === 'TSTCLOSE');
  check(tstclose !== undefined && tstclose.children.size === 8, `suite TSTCLOSE with 8 test cases (${tstclose?.children.size})`);
  check(state('installment for 100,000 at 36% a year over 12 months') === 'passed', `TSTLOAN installment: ${state('installment for 100,000 at 36% a year over 12 months')}`);
  check(state('the control record counts only the transactions') === 'failed', `TSTBATCH seeded defect: ${state('the control record counts only the transactions')}`);
  check(state('the control record is 11 bytes long') === 'passed', `TSTCLOSE with the default dialect: ${state('the control record is 11 bytes long')}`);

  // --- another compiler: the gnucobol-ibm profile chosen through the setting, without a terminal
  const failedNow = () => [...api.tests.lastResults.values()].filter((v) => v === 'failed').length;
  check(failedNow() === 2, `with the default profile 2 test cases fail (${failedNow()})`);
  await vscode.workspace.getConfiguration('cobalto').update('profile', 'gnucobol-ibm', vscode.ConfigurationTarget.Global);
  await api.tests.runAll();
  await api.tests.whenIdle();
  check(failedNow() === 7, `with cobalto.profile = gnucobol-ibm 7 test cases fail (${failedNow()})`);
  check(state('installment for 100,000 at 36% a year over 12 months') === 'failed', `TSTLOAN installment with ibm: ${state('installment for 100,000 at 36% a year over 12 months')}`);
  check(state('the control record is 11 bytes long') === 'failed', `TSTCLOSE control record with ibm: ${state('the control record is 11 bytes long')}`);
  // --- the list of compilers comes from the CLI: the built-in profiles, not only what cblt.json states
  const listed = await readProfiles(projectFor(project)!);
  const profileNames = listed.profiles.map((p) => p.name);
  check(listed.defaultProfile === 'gnucobol' && profileNames.includes('gnucobol-ibm') && profileNames.includes('vms-vsi-cobol'), `profiles from the CLI, default ${listed.defaultProfile} (${profileNames.join(', ')})`);
  // --- the CLI stops before running (a profile that does not exist): the test
  // cases show that error, not the results the previous run left in build/
  const erroredNow = () => [...api.tests.lastResults.values()].filter((v) => v === 'errored').length;
  await vscode.workspace.getConfiguration('cobalto').update('profile', 'nosuch', vscode.ConfigurationTarget.Global);
  await api.tests.runAll();
  await api.tests.whenIdle();
  check(erroredNow() === api.tests.lastResults.size && failedNow() === 0, `with a profile that does not exist every test case is in error (${erroredNow()} of ${api.tests.lastResults.size})`);
  await vscode.workspace.getConfiguration('cobalto').update('profile', undefined, vscode.ConfigurationTarget.Global);
  await api.tests.runAll();
  await api.tests.whenIdle();
  check(failedNow() === 2 && erroredNow() === 0, `back on the default profile 2 test cases fail and none is in error (${failedNow()}, ${erroredNow()})`);

  // --- coverage
  if (!api.coverage.isEnabled()) {
    api.coverage.toggle();
  }
  check(api.coverage.isEnabled(), 'coverage turned on by command');
  check(['cobalto', 'entriesOnly'].includes(api.coverage.marginMode()), `default gutter mode depending on whether Coverage Gutters is installed (${api.coverage.marginMode()})`);
  await vscode.workspace.getConfiguration('cobalto').update('coverage.margin', 'off', vscode.ConfigurationTarget.Global);
  check(api.coverage.marginMode() === 'off', 'cobalto.coverage.margin = off is honored');
  await vscode.workspace.getConfiguration('cobalto').update('coverage.margin', 'cobalto', vscode.ConfigurationTarget.Global);
  check(api.coverage.marginMode() === 'cobalto', 'cobalto.coverage.margin = cobalto is honored');
  await vscode.workspace.getConfiguration('cobalto').update('coverage.margin', undefined, vscode.ConfigurationTarget.Global);
  const discountSrc = path.join(project, 'src', 'DISCOUNT.cbl');
  const doc = await vscode.workspace.openTextDocument(discountSrc);
  await vscode.window.showTextDocument(doc);
  const cov = api.coverage.lcovFor(discountSrc);
  check(cov !== undefined && cov.file.lines.size === 9, `lcov of DISCOUNT.cbl: ${cov?.file.lines.size} statements`);
  const invoice = api.coverage.lcovFor(path.join(project, 'src', 'INVOICE.cbl'));
  check(invoice !== undefined && invoice.file.functions.some((f) => f.name === '0000-MAIN' && f.hits > 0), 'paragraph 0000-MAIN executed in INVOICE.cbl (RUN of the interface test case)');
  const dayclose = api.coverage.lcovFor(path.join(project, 'src', 'DAYCLOSE.cbl'));
  check(dayclose !== undefined && dayclose.file.functions.some((f) => f.name === '0000-MAIN' && f.hits === 0), 'paragraph 0000-MAIN not executed in DAYCLOSE.cbl (no test case uses RUN)');
  // kind of test case (interface / internal) as a JUnit property
  const junit = fs.readFileSync(path.join(project, 'build', 'junit.xml'), 'utf8');
  const kindOf = (name: string): string | undefined =>
    junit.match(new RegExp(`<testcase name="${name.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')}"[^>]*>\\s*<properties><property name="cobalto.kind" value="(\\w+)"`))?.[1];
  check(kindOf('interface: master file goes in, transactions come out') === 'interface', `JUnit: the interface test case of TSTBATCH has cobalto.kind=interface (${kindOf('interface: master file goes in, transactions come out')})`);
  check(kindOf('mocked installment: the batch without the calculation') === 'internal', `JUnit: an internal test case of TSTBATCH has cobalto.kind=internal (${kindOf('mocked installment: the batch without the calculation')})`);
  check(kindOf('one customer: the record goes in, the line comes out') === 'interface', `JUnit: the test case with RUN of TSTIFACE has cobalto.kind=interface (${kindOf('one customer: the record goes in, the line comes out')})`);
  const loancalc = api.coverage.lcovFor(path.join(project, 'src', 'LOANCALC.cbl'));
  check(loancalc !== undefined && [...loancalc.file.lines.values()].every((h) => h > 0) && loancalc.file.functions.length === 7, `LOANCALC.cbl at 100%: ${loancalc?.file.lines.size} statements, ${loancalc?.file.functions.length} paragraphs`);
  check(dayclose !== undefined && [...dayclose.file.lines.values()].some((h) => h === 0), 'DAYCLOSE.cbl with statements not executed (red in the gutter: its 0000-MAIN ends in STOP RUN)');

  // --- coverage per run: the batch suite alone leaves red in LOANCALC.cbl; the whole project turns it green
  const zeros = () => [...(api.coverage.lcovFor(path.join(project, 'src', 'LOANCALC.cbl'))?.file.lines.values() ?? [])].filter((h) => h === 0).length;
  await api.tests.runSuite('TSTBATCH');
  await api.tests.whenIdle();
  check(zeros() === 7, `after TSTBATCH alone, LOANCALC.cbl has 7 statements not executed (${zeros()})`);
  const fcLoan = api.coverage.fileCoverages(projectFor(project)!).find((fc) => fc.uri.fsPath.endsWith('LOANCALC.cbl'));
  check(fcLoan?.branchCoverage?.covered === 26 && fcLoan?.branchCoverage?.total === 42, `Test Coverage view: LOANCALC.cbl branches 26/42 (${fcLoan?.branchCoverage?.covered}/${fcLoan?.branchCoverage?.total})`);
  const brLabels = fcLoan?.details.flatMap((d) => (d instanceof vscode.StatementCoverage ? d.branches : [])).map((b) => b.label ?? '') ?? [];
  check(brLabels.includes('THEN') && brLabels.some((l) => l.startsWith('WHEN LN-TERM-MONTHS')), `the branches carry their label from the map (${brLabels.length} branches, e.g. ${brLabels.slice(0, 3).join(' | ')})`);
  check(api.coverage.isEnabled(), 'coverage in the gutter is still on after the run');
  await api.tests.runAll();
  await api.tests.whenIdle();
  check(zeros() === 0, `after running everything, LOANCALC.cbl is back to 46/46 (${zeros()} not executed)`);

  // --- actual debugging with the cobalto type
  const cblt = path.join(project, 'tests', 'INVOICE.cblt');
  const bpLine = firstLineMatching(cblt, /^\s{7,}PERFORM 2100-CALC/);
  const bp = new vscode.SourceBreakpoint(new vscode.Location(vscode.Uri.file(cblt), new vscode.Position(bpLine - 1, 0)));
  vscode.debug.addBreakpoints([bp]);
  const stops: Record<string, unknown>[] = [];
  const tracker = vscode.debug.registerDebugAdapterTrackerFactory('cobalto', {
    createDebugAdapterTracker: () => ({
      onDidSendMessage: (m: { type: string; event?: string; body?: Record<string, unknown> }) => {
        if (m.type === 'event' && m.event === 'stopped') {
          stops.push(m.body ?? {});
        }
      },
    }),
  });
  const folder = vscode.workspace.workspaceFolders?.[0];
  const started = await vscode.debug.startDebugging(folder, { type: 'cobalto', request: 'launch', name: 'verification', suite: 'TSTINV', cwd: project });
  check(started, 'startDebugging with the cobalto type (includes cobalto debug --suite TSTINV)');
  const session = await waitFor('session', () => vscode.debug.activeDebugSession, 60000);
  check(session?.type === 'cobalto', `active session of type ${session?.type}`);
  if (session) {
    const stop1 = await waitFor('stop at the breakpoint', () => stops[0], 60000);
    check(stop1?.reason === 'breakpoint', `stop 1: ${JSON.stringify(stop1)}`);
    const threadId = stop1?.threadId as number;
    const st = await session.customRequest('stackTrace', { threadId, startFrame: 0, levels: 5 });
    const frames = st.stackFrames as Frame[];
    log('  stack: ' + frames.map((f) => `${f.name}@${f.source?.name}:${f.line}`).join(' > '));
    check(frames[0]?.source?.name === 'INVOICE.cblt' && frames[0].line === bpLine, `top frame at INVOICE.cblt:${bpLine}`);
    check(frames[1]?.presentationHint === 'subtle', 'generated C frame marked as subtle');
    const scopes = await session.customRequest('scopes', { frameId: frames[0].id });
    const globals = (scopes.scopes as { name: string; variablesReference: number }[]).find((s) => s.name === 'Globals');
    const vars = (await session.customRequest('variables', { variablesReference: globals!.variablesReference })).variables as { name: string; value: string }[];
    const ws = vars.find((v) => v.name === 'WS-AMOUNT');
    check(ws !== undefined, `Globals shows WS-AMOUNT = ${ws?.value}`);
    check(!vars.some((v) => /^b_\d+$/.test(v.name)), 'no b_NNN in the variables panel');
    const ev = await session.customRequest('evaluate', { expression: 'WS-C-AMOUNT', frameId: frames[0].id, context: 'hover' });
    check(/2000/.test(String(ev.result)), `hover WS-C-AMOUNT = ${ev.result}`);
    // what VS Code sends to the hover: the whole COBOL name, not the word cut at the hyphens
    const doc = await vscode.workspace.openTextDocument(cblt);
    const moveLine = bpLine - 1; // MOVE 2000 TO WS-C-AMOUNT, right before the PERFORM
    const col = doc.lineAt(moveLine - 1).text.indexOf('WS-C-AMOUNT') + 5;
    const expr = api.expressionAt(doc, new vscode.Position(moveLine - 1, col));
    check(expr === 'WS-C-AMOUNT', `expression under the cursor at ${path.basename(cblt)}:${moveLine} col ${col + 1} = ${expr}`);
    const watch = await session.customRequest('evaluate', { expression: 'WS-NET', frameId: frames[0].id, context: 'watch' });
    check(/^"?\d+\.\d+"?$/.test(String(watch.result)), `watch WS-NET = ${watch.result}`);
    const n = stops.length;
    await session.customRequest('next', { threadId });
    const stop2 = await waitFor('stop by step', () => stops[n], 30000);
    const st2 = await session.customRequest('stackTrace', { threadId, startFrame: 0, levels: 1 });
    const f2 = (st2.stackFrames as Frame[])[0];
    check(stop2?.reason === 'step' && /\.cbl$/.test(f2?.source?.name ?? ''), `next lands on ${f2?.source?.name}:${f2?.line}`);
    await vscode.debug.stopDebugging(session);
  }
  vscode.debug.removeBreakpoints([bp]);
  await waitFor('end of the first session', () => vscode.debug.activeDebugSession === undefined || undefined, 15000);

  // --- second session: TSTCLOSE with a COBOL condition on an
  // occurrence, OCCURS expanded in the panel and a value change
  const closeCblt = path.join(project, 'tests', 'DAYCLOSE.cblt');
  const closeDoc = fs.readFileSync(closeCblt, 'utf8').split('\n');
  const performLines = closeDoc.map((l, i) => (/^\s{7,}PERFORM CLOSE-DAY THRU CLOSE-EXIT/.test(l) ? i + 1 : 0)).filter((n) => n > 0);
  check(performLines.length >= 2, `DAYCLOSE.cblt with several PERFORM CLOSE-DAY (${performLines.length})`);
  const [case1Line, case2Line] = performLines;
  const cond = 'WS-MOV-AMOUNT(3) > 50000';
  const bps = [case1Line, case2Line].map((ln) => new vscode.SourceBreakpoint(new vscode.Location(vscode.Uri.file(closeCblt), new vscode.Position(ln - 1, 0)), true, cond));
  vscode.debug.addBreakpoints(bps);
  const n2 = stops.length;
  const started2 = await vscode.debug.startDebugging(folder, { type: 'cobalto', request: 'launch', name: 'verification TSTCLOSE', suite: 'TSTCLOSE', cwd: project });
  check(started2, 'startDebugging TSTCLOSE (includes cobalto debug --suite TSTCLOSE)');
  const session2 = await waitFor('session TSTCLOSE', () => vscode.debug.activeDebugSession, 60000);
  if (session2) {
    const stop = await waitFor('stop with the true COBOL condition', () => stops[n2], 60000);
    check(stop?.reason === 'breakpoint', `stop: ${JSON.stringify(stop)}`);
    const threadId = stop?.threadId as number;
    const st = await session2.customRequest('stackTrace', { threadId, startFrame: 0, levels: 3 });
    const frames = st.stackFrames as Frame[];
    log('  stack: ' + frames.map((f) => `${f.name}@${f.source?.name}:${f.line}`).join(' > '));
    check(frames[0]?.source?.name === 'DAYCLOSE.cblt' && frames[0].line === case2Line, `the condition '${cond}' is false at DAYCLOSE.cblt:${case1Line} and stops at :${case2Line} (stopped at :${frames[0]?.line})`);
    const scopes = await session2.customRequest('scopes', { frameId: frames[0].id });
    const globals = (scopes.scopes as { name: string; variablesReference: number }[]).find((s) => s.name === 'Globals');
    type Var = { name: string; value: string; variablesReference: number; indexedVariables?: number };
    const vars = (await session2.customRequest('variables', { variablesReference: globals!.variablesReference })).variables as Var[];
    const movCount = vars.find((v) => v.name === 'WS-MOV-COUNT');
    check(movCount !== undefined && /^\d+$/.test(movCount.value), `WS-MOV-COUNT (COMP) formatted: ${movCount?.value}`);
    const movements = vars.find((v) => v.name === 'WS-MOVEMENTS');
    check(movements !== undefined && movements.variablesReference > 0, 'WS-MOVEMENTS is an expandable group');
    const movKids = movements ? (await session2.customRequest('variables', { variablesReference: movements.variablesReference })).variables as Var[] : [];
    const mov = movKids.find((v) => v.name === 'WS-MOV');
    check(mov !== undefined && mov.variablesReference > 0, `WS-MOV is an expandable OCCURS (${mov?.value})`);
    const occ = mov ? (await session2.customRequest('variables', { variablesReference: mov.variablesReference })).variables as Var[] : [];
    const mov3 = occ.find((v) => v.name === 'WS-MOV(3)');
    check(occ.length >= 50 && mov3 !== undefined && mov3.variablesReference > 0, `occurrences WS-MOV(1)..(${occ.length}), WS-MOV(3) expandable`);
    const fields = mov3 ? (await session2.customRequest('variables', { variablesReference: mov3.variablesReference })).variables as Var[] : [];
    const amount = fields.find((v) => v.name === 'WS-MOV-AMOUNT');
    const channel = fields.find((v) => v.name === 'WS-MOV-CHANNEL');
    check(amount?.value === '000050000.01' && /ATM/.test(channel?.value ?? ''), `WS-MOV(3): WS-MOV-CHANNEL = ${channel?.value}, WS-MOV-AMOUNT = ${amount?.value}`);
    const hover = await session2.customRequest('evaluate', { expression: 'WS-MOV-AMOUNT(3)', frameId: frames[0].id, context: 'hover' });
    check(/50000\.01/.test(String(hover.result)), `hover WS-MOV-AMOUNT(3) = ${hover.result}`);
    // double click on the value in the panel: setVariable on the occurrence
    const sv = await session2.customRequest('setVariable', { variablesReference: mov3!.variablesReference, name: 'WS-MOV-AMOUNT', value: '49999.99' });
    check(sv.value === '000049999.99', `setVariable WS-MOV-AMOUNT of WS-MOV(3) = 49999.99 -> ${sv.value}`);
    const after = await session2.customRequest('evaluate', { expression: 'WS-MOV-AMOUNT(3)', frameId: frames[0].id, context: 'watch' });
    check(/49999\.99/.test(String(after.result)), `watch after the change = ${after.result}`);
    await session2.customRequest('setVariable', { variablesReference: mov3!.variablesReference, name: 'WS-MOV-AMOUNT', value: '50000.01' });
    const total = await session2.customRequest('evaluate', { expression: 'WS-TOTAL-DEBITS', frameId: frames[0].id, context: 'watch' });
    check(/^[+-]?\d+\.\d{2}$/.test(String(total.result)), `watch WS-TOTAL-DEBITS (signed COMP) = ${total.result}`);
    const n3 = stops.length;
    await session2.customRequest('stepIn', { threadId });
    const stop3 = await waitFor('stop by step into', () => stops[n3], 30000);
    const st3 = await session2.customRequest('stackTrace', { threadId, startFrame: 0, levels: 1 });
    const f3 = (st3.stackFrames as Frame[])[0];
    check(stop3?.reason === 'step' && f3?.source?.name === 'DAYCLOSE.cbl', `step into the PERFORM lands on ${f3?.source?.name}:${f3?.line}`);
    await vscode.debug.stopDebugging(session2);
  }
  vscode.debug.removeBreakpoints(bps);
  await waitFor('end of the second session', () => vscode.debug.activeDebugSession === undefined || undefined, 15000);

  // --- third session: debug the failing test case of
  // TSTBATCH up to the MOVE of the seeded defect in 2600-WRITE-TRAILER
  const batchCblt = path.join(project, 'tests', 'LOANBTCH.cblt');
  const endLine = firstLineMatching(batchCblt, /^\s{7,}PERFORM 3000-END/);
  const bp3 = new vscode.SourceBreakpoint(new vscode.Location(vscode.Uri.file(batchCblt), new vscode.Position(endLine - 1, 0)));
  vscode.debug.addBreakpoints([bp3]);
  const n4 = stops.length;
  const started3 = await vscode.debug.startDebugging(folder, { type: 'cobalto', request: 'launch', name: 'verification TSTBATCH', suite: 'TSTBATCH', cwd: project });
  check(started3, 'startDebugging TSTBATCH (includes cobalto debug --suite TSTBATCH)');
  const session3 = await waitFor('session TSTBATCH', () => vscode.debug.activeDebugSession, 60000);
  if (session3) {
    const stop = await waitFor('stop at PERFORM 3000-END', () => stops[n4], 60000);
    const threadId = stop?.threadId as number;
    let st = await session3.customRequest('stackTrace', { threadId, startFrame: 0, levels: 1 });
    let f = (st.stackFrames as Frame[])[0];
    check(stop?.reason === 'breakpoint' && f?.source?.name === 'LOANBTCH.cblt' && f.line === endLine, `stopped at LOANBTCH.cblt:${endLine} (${f?.source?.name}:${f?.line})`);
    const batchSrc = path.join(project, 'src', 'LOANBTCH.cbl');
    const moveLine = firstLineMatching(batchSrc, /MOVE WS-LINE-COUNT TO WS-T-COUNT/);
    const visited: string[] = [];
    for (let i = 0; i < 4 && !(f?.source?.name === 'LOANBTCH.cbl' && f.line === moveLine); i++) {
      const k = stops.length;
      await session3.customRequest('stepIn', { threadId });
      await waitFor('stop by step into', () => stops[k], 30000);
      st = await session3.customRequest('stackTrace', { threadId, startFrame: 0, levels: 1 });
      f = (st.stackFrames as Frame[])[0];
      visited.push(`${f?.source?.name}:${f?.line}`);
    }
    check(f?.source?.name === 'LOANBTCH.cbl' && f.line === moveLine, `F11 leads to the MOVE of the defect at LOANBTCH.cbl:${moveLine} (${visited.join(' > ')})`);
    const lineCount = await session3.customRequest('evaluate', { expression: 'WS-LINE-COUNT', frameId: f.id, context: 'watch' });
    const debitCount = await session3.customRequest('evaluate', { expression: 'WS-DEBIT-COUNT', frameId: f.id, context: 'watch' });
    check(String(lineCount.result) === '00003' && String(debitCount.result) === '00002', `Watch WS-LINE-COUNT = ${lineCount.result}, WS-DEBIT-COUNT = ${debitCount.result}`);
    await vscode.debug.stopDebugging(session3);
  }
  tracker.dispose();
  vscode.debug.removeBreakpoints([bp3]);
  const outDir = path.join(project, 'build');
  fs.writeFileSync(path.join(outDir, 'vscode-verify.log'), lines.join('\n') + '\n');
  log(failures ? `${failures} checks failed` : 'all verified in VS Code');
  if (failures) {
    throw new Error(`${failures} checks failed`);
  }
}
