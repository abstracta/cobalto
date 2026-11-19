// Table test for src/dap/layout.ts: formatting and encoding of COBOL fields,
// references with subscripts and conditions. The part that depends on
// GnuCOBOL's actual encoding is checked against the compiler: a generated
// program with the fields of the table writes its record to a file and the
// layout comes from the same symbol listing that "cobalto debug" uses; the test
// formats those bytes and encodes the value again expecting the same bytes.
//   node out/test/verify-layout.js            (without cobc, only the pure part)
// Needs python3 (the listing parser lives in src/cobalto/debuginfo.py).

import { execFileSync, spawnSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { conditionNames, decimalToString, encodeValue, evalCondition, formatValue, Layout, LayoutItem, offsetOf, Operand, operandOf, parseDecimal, parseReference, rescale } from '../dap/layout';

let failures = 0;
let total = 0;

function check(cond: unknown, label: string): void {
  total++;
  console.log(`  ${cond ? 'OK  ' : 'FAIL'} ${label}`);
  if (!cond) {
    failures++;
  }
}

function throws(fn: () => unknown, re: RegExp, label: string): void {
  try {
    const v = fn();
    check(false, `${label} (did not throw: ${JSON.stringify(v)})`);
  } catch (e) {
    const m = e instanceof Error ? e.message : String(e);
    check(re.test(m), `${label} (${m})`);
  }
}

function item(partial: Partial<LayoutItem> & { kind: LayoutItem['kind']; size: number }): LayoutItem {
  return { name: 'X', level: 5, section: 'WORKING-STORAGE', pic: '', usage: 'DISPLAY', occurs: 0, redefines: null, digits: 0, scale: 0, signed: false, offset: 0, children: [], ...partial };
}

// ------------------------------------------------------------- pure part
function pure(): void {
  console.log('references and decimals');
  check(JSON.stringify(parseReference('WS-T-QTY(2)')) === JSON.stringify({ name: 'WS-T-QTY', subscripts: [2] }), 'parseReference with one subscript');
  check(JSON.stringify(parseReference('ws-n-val (1, 2)')?.subscripts) === '[1,2]', 'parseReference with two subscripts and lowercase');
  check(parseReference('1234') === undefined, 'parseReference rejects a number');
  check(parseReference('b_32[0]') === undefined, 'parseReference rejects a C expression');
  const row: LayoutItem = item({ kind: 'group', size: 12, occurs: 3, name: 'ROW', offset: 11 });
  const val: LayoutItem = item({ kind: 'display', size: 4, digits: 3, signed: true, name: 'VAL', offset: 11 });
  const table: LayoutItem = item({ kind: 'group', size: 24, occurs: 2, name: 'TAB', offset: 11 });
  const loc = { root: table, item: val, dims: [table, row] };
  check(offsetOf(loc, [1, 1]).offset === 11, 'offsetOf (1,1) = base');
  check(offsetOf(loc, [2, 3]).offset === 11 + 24 + 2 * 12, 'offsetOf (2,3) adds both dimensions');
  check(offsetOf(loc, []).offset === 11, 'offsetOf without subscripts takes the first occurrence');
  check(offsetOf(loc, [1, 2, 3]).error !== undefined, 'offsetOf with more subscripts than dimensions reports an error');
  throws(() => offsetOf(loc, [3, 1]), /out of range 1\.\.2/, 'offsetOf out of range');
  check(parseDecimal('-12.50')?.value === -1250n && parseDecimal('-12.50')?.scale === 2, 'parseDecimal with sign and decimals');
  check(parseDecimal('.5')?.value === 5n, 'parseDecimal .5');
  check(parseDecimal('abc') === undefined && parseDecimal('') === undefined, 'parseDecimal rejects text');
  check(rescale({ value: 125n, scale: 1 }, 3) === 12500n && rescale({ value: 12567n, scale: 3 }, 1) === 125n, 'rescale scales up and truncates');
  check(decimalToString({ value: -1250n, scale: 2 }) === '-12.50' && decimalToString({ value: 5n, scale: 0 }) === '5', 'decimalToString');

  console.log('formatting of synthetic bytes');
  check(formatValue(Buffer.from('12'), item({ kind: 'display', size: 3, digits: 3 })) === '(2 of 3 bytes readable)', 'short buffer');
  check(formatValue(Buffer.from('0012345'), item({ kind: 'display', size: 7, digits: 7, scale: 2 })) === '00123.45', 'unsigned DISPLAY with scale');
  check(formatValue(Buffer.from('001234u'), item({ kind: 'display', size: 7, digits: 7, scale: 2, signed: true })) === '-00123.45', 'negative DISPLAY, ASCII overpunch (u = 5)');
  check(formatValue(Buffer.from('001234N'), item({ kind: 'display', size: 7, digits: 7, scale: 2, signed: true })) === '-00123.45', 'negative DISPLAY, EBCDIC overpunch (N = 5)');
  check(formatValue(Buffer.from('001234E'), item({ kind: 'display', size: 7, digits: 7, scale: 2, signed: true })) === '00123.45', 'positive DISPLAY, EBCDIC overpunch (E = 5)');
  check(formatValue(Buffer.from([0x12, 0x3d]), item({ kind: 'comp3', size: 2, digits: 3 })) === '-123', 'negative COMP-3');
  check(formatValue(Buffer.from([0x00, 0x4c]), item({ kind: 'comp3', size: 2, digits: 3 })) === '004', 'positive COMP-3 with padding');
  check(formatValue(Buffer.from([0xff, 0xff, 0xff, 0x9c]), item({ kind: 'binary', size: 4, digits: 9, signed: true })) === '-000000100', 'negative big-endian COMP');
  check(formatValue(Buffer.from([0xfe, 0xff]), item({ kind: 'comp5', size: 2, digits: 4, signed: true })) === '-0002', 'negative little-endian COMP-5');
  check(formatValue(Buffer.from('ab\x01"c'), item({ kind: 'alnum', size: 5 })) === '"ab.\\"c"', 'alphanumeric in quotes with the control character and the quote escaped');

  console.log('encoding: rejections');
  throws(() => encodeValue('100000', item({ kind: 'display', size: 5, digits: 5 })), /does not fit in 5 digits/, 'PIC overflow');
  throws(() => encodeValue('-1', item({ kind: 'display', size: 5, digits: 5 })), /is unsigned/, 'negative value in an unsigned field');
  throws(() => encodeValue('hello', item({ kind: 'comp3', size: 3, digits: 5 })), /is not a number/, 'text in a numeric field');
  const tr = encodeValue('-5', item({ kind: 'display', size: 4, digits: 3, signed: true, sign_separate: true }), Buffer.from('012+'));
  check(tr.toString('latin1') === '005-', 'separate sign keeps its position (trailing)');
  const ld = encodeValue('-5', item({ kind: 'display', size: 4, digits: 3, signed: true, sign_separate: true }), Buffer.from('+012'));
  check(ld.toString('latin1') === '-005', 'separate sign keeps its position (leading)');
  check(encodeValue("'ab'", item({ kind: 'alnum', size: 4 })).toString('latin1') === 'ab  ', 'alphanumeric without quotes and with padding');
  check(encodeValue('abcdefg', item({ kind: 'alnum', size: 4 })).toString('latin1') === 'abcd', 'truncated alphanumeric');

  console.log('conditions');
  const vars: Record<string, Operand> = {
    'WS-NET': { kind: 'number', value: { value: 160000n, scale: 2 } },
    'WS-CAT': { kind: 'text', value: 'PREMIUM   ' },
    'WS-ROW': { kind: 'number', value: { value: 7n, scale: 0 } },
  };
  const resolve = (ref: { name: string; subscripts: number[] }): Operand | undefined => (ref.name === 'WS-ROW' && ref.subscripts[0] !== 2 ? undefined : vars[ref.name]);
  const ev = (c: string): boolean => evalCondition(c, resolve);
  check(ev('WS-NET = 1600') && ev('WS-NET = 1600.00') && !ev('WS-NET = 1600.01'), 'exact numeric with a different scale');
  check(ev("WS-CAT = 'PREMIUM'") && ev('WS-CAT = "PREMIUM   "') && !ev("WS-CAT = 'PREMIUN'"), 'text with space padding');
  check(ev('WS-NET > 1000 AND WS-CAT = "PREMIUM"') && !ev('WS-NET > 2000 AND WS-CAT = "PREMIUM"'), 'AND');
  check(ev('WS-NET > 2000 OR WS-CAT = "PREMIUM"') && !ev('WS-NET > 2000 OR WS-CAT = "X"'), 'OR');
  check(ev('WS-NET > 2000 OR WS-NET < 1700 AND WS-CAT = "PREMIUM"'), 'AND before OR');
  check(ev('NOT WS-NET = 1') && !ev('NOT (WS-NET = 1600 OR WS-NET = 1)'), 'NOT and parentheses');
  check(ev('WS-NET EQUAL TO 1600') && ev('WS-NET IS GREATER THAN 1599') && ev('WS-NET NOT LESS THAN 1600') && ev('WS-NET GREATER THAN OR EQUAL TO 1600'), 'operators as words');
  check(ev('WS-NET >= 1600') && ev('WS-NET <= 1600') && ev('WS-NET <> 1') && ev('WS-NET != 1'), 'operators as symbols');
  check(ev('WS-ROW(2) = 7'), 'subscript in a condition');
  throws(() => ev('WS-ROW(1) = 7'), /is not a field/, 'unresolved name');
  throws(() => ev('WS-NET = 1600 WS-CAT'), /unexpected trailing/, 'extra token');
  throws(() => ev('WS-NET ='), /incomplete/, 'incomplete condition');
  check(JSON.stringify(conditionNames('WS-NET > 1000 AND NOT WS-CAT = "X"')) === '["WS-NET","WS-CAT"]', 'conditionNames without keywords or literals');
  check(conditionNames('b_32[0] == 1').length === 0 || !conditionNames('b_32[0] == 1').includes('AND'), 'conditionNames on a C expression');
  const op = operandOf(Buffer.from('001234u'), item({ kind: 'display', size: 7, digits: 7, scale: 2, signed: true }));
  check(op.kind === 'number' && op.value.value === -12345n && op.value.scale === 2, 'numeric operandOf');
  const opt = operandOf(Buffer.from('AB  '), item({ kind: 'alnum', size: 4 }));
  check(opt.kind === 'text' && opt.value === 'AB  ', 'text operandOf without quotes');
}

// --------------------------------------------------- against the real GnuCOBOL
interface Row {
  /** field name and COBOL declaration (without the level) */
  name: string;
  decl: string;
  /** statement that loads the value (or VALUE in the declaration) */
  move?: string;
  /** expected formatted value */
  expect: string;
  /** text to encode to reproduce the same bytes (expect by default) */
  input?: string;
  subscripts?: number[];
}

const ROWS: Row[] = [
  { name: 'F-DISP-U', decl: 'PIC 9(5)V99 VALUE 123.45', expect: '00123.45' },
  { name: 'F-DISP-N', decl: 'PIC S9(5)V99 VALUE -123.45', expect: '-00123.45' },
  { name: 'F-DISP-P', decl: 'PIC S9(5)V99 VALUE 123.45', expect: '00123.45' },
  { name: 'F-LEAD', decl: 'PIC S9(3) SIGN LEADING SEPARATE VALUE -7', expect: '-007' },
  { name: 'F-TRAIL', decl: 'PIC S9(3) SIGN TRAILING SEPARATE VALUE 12', expect: '012' },
  { name: 'F-TRAIL-N', decl: 'PIC S9(3) SIGN TRAILING SEPARATE VALUE -12', expect: '-012' },
  { name: 'F-COMP3', decl: 'PIC S9(7)V99 COMP-3 VALUE -1234567.89', expect: '-1234567.89' },
  { name: 'F-COMP3-P', decl: 'PIC S9(7)V99 COMP-3 VALUE 1234567.89', expect: '1234567.89' },
  { name: 'F-COMP3-U', decl: 'PIC 9(3) COMP-3 VALUE 42', expect: '042' },
  { name: 'F-BIN', decl: 'PIC S9(9) COMP VALUE -100000', expect: '-000100000' },
  { name: 'F-BIN-U', decl: 'PIC 9(4) COMP VALUE 1234', expect: '1234' },
  { name: 'F-BIN-S', decl: 'PIC S9(4)V9 COMP VALUE -12.5', expect: '-0012.5' },
  { name: 'F-C5', decl: 'PIC S9(4) COMP-5 VALUE -2', expect: '-0002' },
  { name: 'F-ALNUM', decl: 'PIC X(6) VALUE "AB"', expect: '"AB    "', input: 'AB' },
  { name: 'F-EDIT', decl: 'PIC ZZ9.99', move: 'MOVE 3.5 TO F-EDIT', expect: '"  3.50"', input: '  3.50' },
  { name: 'F-DOUBLE', decl: 'COMP-2 VALUE 1.5', expect: '1.5' },
  { name: 'F-FLOAT', decl: 'COMP-1 VALUE 2.5', expect: '2.5' },
  { name: 'F-OCC', decl: 'PIC 9(2) OCCURS 3', move: 'MOVE 7 TO F-OCC(2)', expect: '07', subscripts: [2] },
  { name: 'F-OCC', decl: '', move: '', expect: '00', subscripts: [3] },
  { name: 'F-G1', decl: 'PIC X(2) VALUE "ab"', expect: '"ab"', input: 'ab' },
  { name: 'F-G2', decl: 'PIC 9(2) VALUE 9', expect: '09' },
];

function program(): string {
  const lines = [
    '       IDENTIFICATION DIVISION.',
    '       PROGRAM-ID. LAYTEST.',
    '       ENVIRONMENT DIVISION.',
    '       INPUT-OUTPUT SECTION.',
    '       FILE-CONTROL.',
    '           SELECT OUT-FILE ASSIGN TO "layout.bin"',
    '               ORGANIZATION IS SEQUENTIAL.',
    '       DATA DIVISION.',
    '       FILE SECTION.',
    '       FD  OUT-FILE.',
    '       01  OUT-REC                   PIC X(200).',
    '       WORKING-STORAGE SECTION.',
    '       01  WS-REC.',
  ];
  const seen = new Set<string>();
  for (const r of ROWS) {
    if (!r.decl || seen.has(r.name)) {
      continue;
    }
    seen.add(r.name);
    if (r.name === 'F-G1') {
      lines.push('           05  F-GRP.');
    }
    const level = r.name.startsWith('F-G') ? '10' : '05';
    lines.push(`           ${level}  ${r.name.padEnd(12)} ${r.decl}.`);
  }
  lines.push('       PROCEDURE DIVISION.', '       0000-MAIN.');
  for (const r of ROWS) {
    if (r.move) {
      lines.push(`           ${r.move}`);
    }
  }
  lines.push('           OPEN OUTPUT OUT-FILE', '           MOVE WS-REC TO OUT-REC', '           WRITE OUT-REC', '           CLOSE OUT-FILE', '           GOBACK.');
  return lines.join('\n') + '\n';
}

function withCobc(): void {
  const cobc = spawnSync('cobc', ['--version']);
  if (cobc.error || cobc.status !== 0) {
    console.log('  (no cobc: skipping the check against GnuCOBOL)');
    return;
  }
  const packages = path.resolve(__dirname, '..', '..', '..', 'src');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cobalto-layout-'));
  const src = path.join(dir, 'LAYTEST.cbl');
  fs.writeFileSync(src, program());
  const lst = path.join(dir, 'LAYTEST.lst');
  execFileSync('cobc', ['-x', '-std=default', '-t', lst, '-ftsymbols', '-o', path.join(dir, 'laytest'), src], { cwd: dir, stdio: ['ignore', 'ignore', 'inherit'] });
  execFileSync(path.join(dir, 'laytest'), [], { cwd: dir });
  const bytes = fs.readFileSync(path.join(dir, 'layout.bin'));
  // the layout the same way cobalto debug builds it: symbol listing -> build_layout
  const py = [
    'import sys, json',
    `sys.path.insert(0, ${JSON.stringify(packages)})`,
    'from cobalto import debuginfo',
    `progs = debuginfo.parse_symbol_listing(open(${JSON.stringify(lst)}, encoding="utf-8", errors="replace").read())`,
    'out = {}',
    'for prog, items in progs.items():',
    '    roots, warns = debuginfo.build_layout(items)',
    '    out[prog] = {"source": "LAYTEST.cbl", "items": roots, "warnings": warns}',
    'json.dump({"suite": "LAYTEST", "programs": out}, sys.stdout)',
  ].join('\n');
  const jsonPath = path.join(dir, 'LAYTEST.layout.json');
  fs.writeFileSync(jsonPath, execFileSync('python3', ['-'], { input: py }));
  const layout = Layout.load(jsonPath);
  check(layout !== undefined, 'layout loaded from the symbol listing');
  const rec = layout?.root('LAYTEST', 'WS-REC');
  check(rec !== undefined && (rec.unreliable ?? false) === false, `WS-REC of ${rec?.size} bytes without inconsistencies`);
  check(rec !== undefined && bytes.length >= rec.size, `record written by the program: ${bytes.length} bytes`);
  console.log(`actual GnuCOBOL bytes (${dir})`);
  for (const r of ROWS) {
    const loc = layout?.find('LAYTEST', r.name);
    if (!loc) {
      check(false, `${r.name}: not in the layout`);
      continue;
    }
    const { offset } = offsetOf(loc, r.subscripts ?? []);
    const slice = bytes.subarray(offset, offset + loc.item.size);
    const got = formatValue(slice, loc.item);
    const label = r.subscripts ? `${r.name}(${r.subscripts.join(',')})` : r.name;
    check(got === r.expect, `${label} [${loc.item.kind}, ${loc.item.pic || loc.item.usage}, +${offset}] = ${got}`);
    if (r.decl.includes('COMP-1') || r.decl.includes('COMP-2')) {
      continue; // floats: byte equality depends on how the literal is rounded
    }
    try {
      const enc = encodeValue(r.input ?? r.expect, loc.item, slice);
      check(enc.equals(slice), `${label}: encoding "${r.input ?? r.expect}" reproduces cobc's bytes (${slice.toString('hex')})`);
    } catch (e) {
      check(false, `${label}: encoding failed: ${String(e)}`);
    }
  }
  // round trip of a new value over each numeric encoding
  for (const [name, text, expect] of [['F-DISP-N', '-99999.99', '-99999.99'], ['F-COMP3', '-0.01', '-0000000.01'], ['F-BIN', '123', '000000123'], ['F-C5', '-9999', '-9999'], ['F-LEAD', '-999', '-999'], ['F-TRAIL', '-1', '-001']]) {
    const loc = layout!.find('LAYTEST', name)!;
    const { offset } = offsetOf(loc, []);
    const enc = encodeValue(text, loc.item, bytes.subarray(offset, offset + loc.item.size));
    check(formatValue(enc, loc.item) === expect, `${name}: round trip of ${text} = ${formatValue(enc, loc.item)}`);
  }
  fs.rmSync(dir, { recursive: true, force: true });
}

pure();
withCobc();
console.log(failures ? `\n${failures} of ${total} checks failed` : `\nall verified (${total} checks)`);
process.exit(failures ? 1 : 0);
