// Unit tests for src/dap/line-map.ts: the map between the lines of a generated
// source and their origin (build/<suite>.lines.json).

import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { after, before, describe, test } from 'node:test';
import { LineMap } from '../../dap/line-map';
import { SUPPORTED_SCHEMA } from '../../dap/schema';

/** The project folder the relative paths of the map start at (it need not exist). */
const ROOT = path.resolve('/work/billing');
const inRoot = (relative: string): string => path.resolve(ROOT, relative);

// build/TSTINV.cbl is an in-program copy: lines of the program, a generated
// line without origin and the statements of the .cblt (line 18 expands into
// two generated lines). build/INVOICEAI.cbl copies the same program.
const ORIGINS = {
  'build/TSTINV.cbl': [
    ['src/INVOICE.cbl', 1],
    ['src/INVOICE.cbl', 2],
    null,
    ['tests/INVOICE.cblt', 18],
    ['tests/INVOICE.cblt', 18],
    ['tests/INVOICE.cblt', 19],
  ],
  'build/INVOICEAI.cbl': [
    null,
    ['src/INVOICE.cbl', 1],
    ['tests/INVOICE.ai.cblt', 21],
  ],
};

describe('LineMap', () => {
  let tmp = '';
  let count = 0;

  before(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cobalto-line-map-'));
  });

  after(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  function write(content: string): string {
    const file = path.join(tmp, `map-${++count}.lines.json`);
    fs.writeFileSync(file, content);
    return file;
  }

  function load(document: unknown = { schema: SUPPORTED_SCHEMA, cobalto: '0.7.0', suite: 'TSTINV', origins: ORIGINS }): LineMap {
    const map = LineMap.load(write(JSON.stringify(document)), ROOT);
    assert.ok(map, 'the map should load');
    return map;
  }

  describe('from a generated line to its origin', () => {
    test('a generated line maps to the file and line it comes from', () => {
      assert.deepEqual(load().originOf(inRoot('build/TSTINV.cbl'), 6), { file: inRoot('tests/INVOICE.cblt'), line: 19 });
    });

    test('the first line of a generated file is line 1', () => {
      assert.deepEqual(load().originOf(inRoot('build/TSTINV.cbl'), 1), { file: inRoot('src/INVOICE.cbl'), line: 1 });
    });

    test('every generated line of one statement maps to the same origin line', () => {
      const map = load();
      const expected = { file: inRoot('tests/INVOICE.cblt'), line: 18 };
      assert.deepEqual(map.originOf(inRoot('build/TSTINV.cbl'), 4), expected);
      assert.deepEqual(map.originOf(inRoot('build/TSTINV.cbl'), 5), expected);
    });

    test('a generated line without origin has none', () => {
      assert.equal(load().originOf(inRoot('build/TSTINV.cbl'), 3), undefined);
    });

    test('a line outside the generated file has no origin', () => {
      const map = load();
      assert.equal(map.originOf(inRoot('build/TSTINV.cbl'), 0), undefined);
      assert.equal(map.originOf(inRoot('build/TSTINV.cbl'), 7), undefined);
    });

    test('a file that is not generated has no origin', () => {
      assert.equal(load().originOf(inRoot('src/INVOICE.cbl'), 1), undefined);
    });

    test('each generated file has its own lines', () => {
      assert.deepEqual(load().originOf(inRoot('build/INVOICEAI.cbl'), 3), { file: inRoot('tests/INVOICE.ai.cblt'), line: 21 });
    });
  });

  describe('from an origin line to the generated one', () => {
    test('an origin line maps to its generated line', () => {
      const lines = load().generatedFor(inRoot('tests/INVOICE.cblt'))?.get(inRoot('build/TSTINV.cbl'));
      assert.equal(lines?.get(19), 6);
    });

    test('an origin line that expands into several generated lines maps to the first', () => {
      const lines = load().generatedFor(inRoot('tests/INVOICE.cblt'))?.get(inRoot('build/TSTINV.cbl'));
      assert.equal(lines?.get(18), 4);
    });

    test('an origin line that generated nothing is not in the map', () => {
      const lines = load().generatedFor(inRoot('tests/INVOICE.cblt'))?.get(inRoot('build/TSTINV.cbl'));
      assert.equal(lines?.has(17), false);
    });

    test('a program copied into two generated files lists both, each with its own line', () => {
      const byGenerated = load().generatedFor(inRoot('src/INVOICE.cbl'));
      assert.ok(byGenerated);
      assert.deepEqual([...byGenerated.keys()].sort(), [inRoot('build/INVOICEAI.cbl'), inRoot('build/TSTINV.cbl')]);
      assert.equal(byGenerated.get(inRoot('build/TSTINV.cbl'))?.get(1), 1);
      assert.equal(byGenerated.get(inRoot('build/INVOICEAI.cbl'))?.get(1), 2);
    });

    test('a file that is the origin of nothing has no generated files', () => {
      assert.equal(load().generatedFor(inRoot('src/DISCOUNT.cbl')), undefined);
    });

    test('going to the generated line and back returns the same origin', () => {
      const map = load();
      const origin = { file: inRoot('tests/INVOICE.cblt'), line: 19 };
      const generated = inRoot('build/TSTINV.cbl');
      const line = map.generatedFor(origin.file)?.get(generated)?.get(origin.line);
      assert.ok(line);
      assert.deepEqual(map.originOf(generated, line), origin);
    });
  });

  describe('generated files', () => {
    test('a generated source is recognized by its absolute path', () => {
      const map = load();
      assert.equal(map.isGenerated(inRoot('build/TSTINV.cbl')), true);
      assert.equal(map.isGenerated(inRoot('build/INVOICEAI.cbl')), true);
    });

    test('an origin file is not a generated source', () => {
      const map = load();
      assert.equal(map.isGenerated(inRoot('src/INVOICE.cbl')), false);
      assert.equal(map.isGenerated(inRoot('tests/INVOICE.cblt')), false);
    });

    test('the generated files are listed with paths resolved against the root', () => {
      assert.deepEqual(load().generatedFiles().sort(), [inRoot('build/INVOICEAI.cbl'), inRoot('build/TSTINV.cbl')]);
    });

    test('an absolute origin path is kept as it is', () => {
      const library = path.resolve('/opt/cobalto/lib/CBLTLIB.cbl');
      const map = load({ schema: SUPPORTED_SCHEMA, origins: { 'build/TSTINV.cbl': [[library, 40]] } });
      assert.deepEqual(map.originOf(inRoot('build/TSTINV.cbl'), 1), { file: library, line: 40 });
    });
  });

  describe('loading', () => {
    test('a file without the schema field (before 0.7.0) is read', () => {
      const map = load({ suite: 'TSTINV', origins: ORIGINS });
      assert.deepEqual(map.originOf(inRoot('build/TSTINV.cbl'), 2), { file: inRoot('src/INVOICE.cbl'), line: 2 });
    });

    test('a file with a newer schema is not used and the reason is logged', () => {
      const file = write(JSON.stringify({ schema: SUPPORTED_SCHEMA + 1, cobalto: '9.1.0', origins: ORIGINS }));
      const log: string[] = [];
      assert.equal(LineMap.load(file, ROOT, (s) => log.push(s)), undefined);
      assert.equal(log.length, 1);
      assert.ok(log[0].includes(file));
      assert.ok(log[0].includes('9.1.0'));
    });

    test('a document without origins loads as an empty map', () => {
      const map = load({ schema: SUPPORTED_SCHEMA, cobalto: '0.7.0', suite: 'TSTINV' });
      assert.deepEqual(map.generatedFiles(), []);
    });

    test('a missing file gives no map', () => {
      assert.equal(LineMap.load(path.join(tmp, 'does-not-exist.lines.json'), ROOT), undefined);
    });

    test('a file that is not JSON gives no map', () => {
      assert.equal(LineMap.load(write('{"schema": 1, "origins": {'), ROOT), undefined);
    });
  });
});
