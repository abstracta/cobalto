// Unit tests for src/suites.ts: the document of `cobalto list --json` as the
// extension uses it.

import assert from 'node:assert/strict';
import * as path from 'node:path';
import { describe, test } from 'node:test';
import { listingFrom } from '../../suites';

const ROOT = path.resolve('/work/billing');

const DSL_SUITE = {
  id: 'TSTINV',
  file: 'tests/INVOICE.cblt',
  line: 4,
  description: 'Invoicing (in-program on INVOICE)',
  dsl: true,
  program: 'INVOICE',
  cases: [
    { name: 'one line calculated with the real DISCOUNT', line: 18, ignored: false },
    { name: 'pending: close with a file error', line: 97, ignored: true },
  ],
};

const COBOL_SUITE = { id: 'TSTCATEG', file: 'tests/TSTCATEG.cbl', line: 2, description: '', dsl: false, program: null, cases: [] };

function document(suites: unknown[], errors?: unknown[]): unknown {
  return { schema: 1, cobalto: '0.7.0', suites, ...(errors ? { errors } : {}) };
}

describe('listingFrom: suites', () => {
  test('a DSL suite keeps its identifier, description, line and program', () => {
    const { suites } = listingFrom(document([DSL_SUITE]), ROOT);
    assert.equal(suites.length, 1);
    const s = suites[0];
    assert.deepEqual([s.id, s.description, s.line, s.program, s.legacy], ['TSTINV', 'Invoicing (in-program on INVOICE)', 4, 'INVOICE', false]);
  });

  test('the cases of a suite keep name, line and the ignored mark', () => {
    const { suites } = listingFrom(document([DSL_SUITE]), ROOT);
    assert.deepEqual(suites[0].cases, [
      { name: 'one line calculated with the real DISCOUNT', line: 18, ignored: false },
      { name: 'pending: close with a file error', line: 97, ignored: true },
    ]);
  });

  test('a DSL suite that names no program has none', () => {
    const { suites } = listingFrom(document([{ ...DSL_SUITE, program: null }]), ROOT);
    assert.equal(suites[0].program, undefined);
  });

  test('a DSL suite without a description has an empty one', () => {
    const { description: _dropped, ...withoutDescription } = DSL_SUITE;
    const { suites } = listingFrom(document([withoutDescription]), ROOT);
    assert.equal(suites[0].description, '');
  });

  test('a COBOL test without the DSL is a legacy suite with no cases', () => {
    const { suites } = listingFrom(document([COBOL_SUITE]), ROOT);
    assert.equal(suites[0].id, 'TSTCATEG');
    assert.equal(suites[0].legacy, true);
    assert.deepEqual(suites[0].cases, []);
    assert.equal(suites[0].program, undefined);
  });

  test('a COBOL test without the DSL is described as such', () => {
    const { suites } = listingFrom(document([COBOL_SUITE]), ROOT);
    assert.match(suites[0].description, /without the DSL/);
  });

  test('a suite the CLI lists without cases has an empty list', () => {
    const { cases: _dropped, ...withoutCases } = DSL_SUITE;
    const { suites } = listingFrom(document([withoutCases]), ROOT);
    assert.deepEqual(suites[0].cases, []);
  });

  test('suites keep the order of the document', () => {
    const { suites } = listingFrom(document([COBOL_SUITE, DSL_SUITE, { ...DSL_SUITE, id: 'TSTIFACE', file: 'tests/INVOICE.iface.cblt' }]), ROOT);
    assert.deepEqual(suites.map((s) => s.id), ['TSTCATEG', 'TSTINV', 'TSTIFACE']);
  });

  test('a relative file is resolved against the project root', () => {
    const { suites } = listingFrom(document([DSL_SUITE, COBOL_SUITE]), ROOT);
    assert.deepEqual(suites.map((s) => s.file), [path.join(ROOT, 'tests', 'INVOICE.cblt'), path.join(ROOT, 'tests', 'TSTCATEG.cbl')]);
  });

  test('an absolute file is kept as it is', () => {
    const elsewhere = path.resolve('/shared/suites/INVOICE.cblt');
    const { suites } = listingFrom(document([{ ...DSL_SUITE, file: elsewhere }]), ROOT);
    assert.equal(suites[0].file, elsewhere);
  });
});

describe('listingFrom: errors', () => {
  const ERROR = { file: 'tests/BROKEN.cblt', line: 12, code: 'CBLT-E101', message: 'TESTCASE without a name' };

  test('an error keeps its line and joins code and message', () => {
    const { errors } = listingFrom(document([], [ERROR]), ROOT);
    assert.equal(errors.length, 1);
    assert.equal(errors[0].line, 12);
    assert.match(errors[0].message, /CBLT-E101/);
    assert.match(errors[0].message, /TESTCASE without a name/);
  });

  test('the file of an error is resolved against the project root', () => {
    const { errors } = listingFrom(document([], [ERROR]), ROOT);
    assert.equal(errors[0].file, path.join(ROOT, 'tests', 'BROKEN.cblt'));
  });

  test('an error without a numeric line points at the first line', () => {
    const { errors } = listingFrom(document([], [{ ...ERROR, line: '?' }]), ROOT);
    assert.equal(errors[0].line, 1);
  });

  test('errors come along with the suites that could be read', () => {
    const listing = listingFrom(document([DSL_SUITE], [ERROR]), ROOT);
    assert.equal(listing.ok, true);
    assert.deepEqual(listing.suites.map((s) => s.id), ['TSTINV']);
    assert.equal(listing.errors.length, 1);
  });

  test('a document without the errors field has no errors', () => {
    const listing = listingFrom(document([DSL_SUITE]), ROOT);
    assert.deepEqual(listing.errors, []);
  });
});

describe('listingFrom: whether the CLI answered', () => {
  test('a document with suites is ok', () => {
    assert.equal(listingFrom(document([DSL_SUITE]), ROOT).ok, true);
  });

  test('a project without suites is ok and empty', () => {
    assert.deepEqual(listingFrom(document([]), ROOT), { ok: true, suites: [], errors: [] });
  });

  test('a missing document is not ok', () => {
    assert.deepEqual(listingFrom(undefined, ROOT), { ok: false, suites: [], errors: [] });
    assert.deepEqual(listingFrom(null, ROOT), { ok: false, suites: [], errors: [] });
  });

  test('a document without a list of suites is not ok', () => {
    assert.equal(listingFrom({}, ROOT).ok, false);
    assert.equal(listingFrom({ schema: 1, suites: 'TSTINV' }, ROOT).ok, false);
    assert.equal(listingFrom({ schema: 1, suites: { TSTINV: DSL_SUITE } }, ROOT).ok, false);
  });

  test('a document that is not an object is not ok', () => {
    assert.equal(listingFrom('TSTINV  tests/INVOICE.cblt', ROOT).ok, false);
    assert.equal(listingFrom([DSL_SUITE], ROOT).ok, false);
  });
});
