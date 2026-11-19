// Unit tests for src/cov-map.ts: the reader of build/cov/map.json.

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { branchLabelsFrom } from '../../cov-map';
import { SUPPORTED_SCHEMA } from '../../dap/schema';

/** The programs of a map as the CLI writes them: only what the reader uses. */
const PROGRAMS = {
  INVOICE: {
    program: 'INVOICE',
    branches: [
      { stmt: 5, kind: 'IF', label: 'THEN', line: 50, file: 'src/INVOICE.cbl', idx: 6, implicit: false },
      { stmt: 5, kind: 'IF', label: 'ELSE', line: 52, file: 'src/INVOICE.cbl', idx: 7, implicit: false },
      { stmt: 17, kind: 'READ', label: 'AT END', line: 64, file: 'src/INVOICE.cbl', idx: 18, implicit: false },
      { stmt: 17, kind: 'READ', label: 'NOT AT END', line: 64, file: 'src/INVOICE.cbl', idx: null, implicit: true },
      { stmt: 21, kind: 'IF', label: 'THEN', line: 9, file: 'src/TOTALS.cpy', idx: 22, implicit: false },
    ],
  },
  DISCOUNT: {
    program: 'DISCOUNT',
    branches: [{ stmt: 5, kind: 'IF', label: 'THEN', line: 23, file: 'src/DISCOUNT.cbl', idx: 6, implicit: false }],
  },
  NOBRANCH: { program: 'NOBRANCH' },
};

const MAP = { schema: SUPPORTED_SCHEMA, cobalto: '0.7.0', programs: PROGRAMS };

describe('branchLabelsFrom', () => {
  test('branches are keyed by file and by statement index and ordinal', () => {
    const { labels, problem } = branchLabelsFrom(MAP, 'build/cov/map.json');
    assert.equal(problem, undefined);
    assert.deepEqual(labels.get('src/INVOICE.cbl')?.get('5:0'), { label: 'THEN', line: 50 });
    assert.deepEqual(labels.get('src/INVOICE.cbl')?.get('5:1'), { label: 'ELSE', line: 52 });
  });

  test('the ordinal counts the branches of one statement in the order of the map', () => {
    const { labels } = branchLabelsFrom(MAP, 'build/cov/map.json');
    assert.deepEqual(labels.get('src/INVOICE.cbl')?.get('17:0'), { label: 'AT END', line: 64 });
    assert.deepEqual(labels.get('src/INVOICE.cbl')?.get('17:1'), { label: 'NOT AT END', line: 64 });
  });

  test('a branch in a copybook goes under the copybook', () => {
    const { labels } = branchLabelsFrom(MAP, 'build/cov/map.json');
    assert.deepEqual(labels.get('src/TOTALS.cpy')?.get('21:0'), { label: 'THEN', line: 9 });
    assert.equal(labels.get('src/INVOICE.cbl')?.has('21:0'), false);
  });

  test('the same statement index in two programs does not collide', () => {
    const { labels } = branchLabelsFrom(MAP, 'build/cov/map.json');
    assert.deepEqual(labels.get('src/DISCOUNT.cbl')?.get('5:0'), { label: 'THEN', line: 23 });
    assert.deepEqual(labels.get('src/INVOICE.cbl')?.get('5:0'), { label: 'THEN', line: 50 });
  });

  test('a program without branches adds nothing', () => {
    const { labels } = branchLabelsFrom(MAP, 'build/cov/map.json');
    assert.deepEqual([...labels.keys()].sort(), ['src/DISCOUNT.cbl', 'src/INVOICE.cbl', 'src/TOTALS.cpy']);
  });

  test('a map from before the schema field has the programs at the top level', () => {
    const { labels, problem } = branchLabelsFrom(PROGRAMS, 'build/cov/map.json');
    assert.equal(problem, undefined);
    assert.deepEqual(labels.get('src/INVOICE.cbl')?.get('5:1'), { label: 'ELSE', line: 52 });
    assert.equal(labels.size, 3);
  });

  test('a map with a newer schema is not used and says why', () => {
    const { labels, problem } = branchLabelsFrom({ ...MAP, schema: SUPPORTED_SCHEMA + 1, cobalto: '9.1.0' }, 'build/cov/map.json');
    assert.equal(labels.size, 0);
    assert.ok(problem);
    assert.ok(problem.includes('build/cov/map.json'));
    assert.ok(problem.includes('9.1.0'));
  });

  test('a map with the schema field and no programs has no branches', () => {
    assert.equal(branchLabelsFrom({ schema: SUPPORTED_SCHEMA }, 'build/cov/map.json').labels.size, 0);
  });

  test('something that is not a map has no branches', () => {
    for (const data of [null, 7, 'text', [PROGRAMS]]) {
      const { labels, problem } = branchLabelsFrom(data, 'build/cov/map.json');
      assert.equal(labels.size, 0);
      assert.equal(problem, undefined);
    }
  });
});
