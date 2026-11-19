// Unit tests for src/lcov.ts: the reader of build/lcov.info.

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { parseLcov } from '../../lcov';

/** One record as the CLI writes it: paragraphs, branches, statements and summaries. */
const INVOICE = [
  'TN:',
  'SF:src/INVOICE.cbl',
  'FN:42,0000-MAIN',
  'FN:57,1000-READ',
  'FN:70,9000-ABORT',
  'FNDA:1,0000-MAIN',
  'FNDA:12,1000-READ',
  'FNDA:0,9000-ABORT',
  'FNF:3',
  'FNH:2',
  'BRDA:50,5,0,7',
  'BRDA:50,5,1,24',
  'BRDA:64,17,0,0',
  'BRDA:64,17,1,-',
  'BRF:4',
  'BRH:2',
  'DA:43,1',
  'DA:44,0',
  'DA:58,12',
  'LF:3',
  'LH:2',
  'end_of_record',
];

const DISCOUNT = [
  'TN:',
  'SF:src/DISCOUNT.cbl',
  'FN:14,0000-MAIN',
  'FNDA:9,0000-MAIN',
  'FNF:1',
  'FNH:1',
  'BRDA:16,2,0,3',
  'BRF:1',
  'BRH:1',
  'DA:15,9',
  'DA:16,9',
  'LF:2',
  'LH:2',
  'end_of_record',
];

function text(...records: string[][]): string {
  return records.flat().join('\n') + '\n';
}

describe('parseLcov: one file', () => {
  test('the path is kept as SF writes it', () => {
    const [file] = parseLcov(text(INVOICE));
    assert.equal(file.path, 'src/INVOICE.cbl');
  });

  test('DA records give the hits of each statement line', () => {
    const [file] = parseLcov(text(INVOICE));
    assert.deepEqual([...file.lines], [[43, 1], [44, 0], [58, 12]]);
  });

  test('a statement that did not run is kept with zero hits', () => {
    const [file] = parseLcov(text(INVOICE));
    assert.equal(file.lines.has(44), true);
    assert.equal(file.lines.get(44), 0);
  });

  test('a line without a DA record is not a statement', () => {
    const [file] = parseLcov(text(INVOICE));
    assert.equal(file.lines.has(45), false);
  });

  test('FN and FNDA give each paragraph its line and its entries', () => {
    const [file] = parseLcov(text(INVOICE));
    assert.deepEqual(file.functions, [
      { name: '0000-MAIN', line: 42, hits: 1 },
      { name: '1000-READ', line: 57, hits: 12 },
      { name: '9000-ABORT', line: 70, hits: 0 },
    ]);
  });

  test('a paragraph without an FNDA record has zero entries', () => {
    const [file] = parseLcov(text(['SF:src/INVOICE.cbl', 'FN:42,0000-MAIN', 'DA:43,1', 'end_of_record']));
    assert.deepEqual(file.functions, [{ name: '0000-MAIN', line: 42, hits: 0 }]);
  });

  test('BRDA records give line, statement, ordinal and times taken of each branch', () => {
    const [file] = parseLcov(text(INVOICE));
    assert.deepEqual(file.branches.slice(0, 2), [
      { line: 50, stmt: 5, ordinal: 0, taken: 7 },
      { line: 50, stmt: 5, ordinal: 1, taken: 24 },
    ]);
  });

  test('a branch whose statement never ran ("-") counts as not taken', () => {
    const [file] = parseLcov(text(INVOICE));
    assert.deepEqual(file.branches.slice(2).map((b) => b.taken), [0, 0]);
  });

  test('summary records and the test name are not data', () => {
    const [file] = parseLcov(text(INVOICE));
    assert.equal(file.lines.size, 3);
    assert.equal(file.functions.length, 3);
    assert.equal(file.branches.length, 4);
  });

  test('a file with statements only has no paragraphs and no branches', () => {
    const [file] = parseLcov(text(['SF:src/PLAIN.cbl', 'DA:10,2', 'end_of_record']));
    assert.deepEqual(file.functions, []);
    assert.deepEqual(file.branches, []);
    assert.deepEqual([...file.lines], [[10, 2]]);
  });
});

describe('parseLcov: the document', () => {
  test('several files come in order, each with its own data', () => {
    const files = parseLcov(text(INVOICE, DISCOUNT));
    assert.deepEqual(files.map((f) => f.path), ['src/INVOICE.cbl', 'src/DISCOUNT.cbl']);
    assert.deepEqual([...files[1].lines], [[15, 9], [16, 9]]);
    assert.deepEqual(files[1].branches, [{ line: 16, stmt: 2, ordinal: 0, taken: 3 }]);
  });

  test('paragraphs with the same name in two files keep separate entries', () => {
    const files = parseLcov(text(INVOICE, DISCOUNT));
    assert.deepEqual(files.map((f) => f.functions.find((fn) => fn.name === '0000-MAIN')), [
      { name: '0000-MAIN', line: 42, hits: 1 },
      { name: '0000-MAIN', line: 14, hits: 9 },
    ]);
  });

  test('CRLF line endings are accepted', () => {
    const files = parseLcov(text(INVOICE, DISCOUNT).replace(/\n/g, '\r\n'));
    assert.deepEqual(files.map((f) => f.path), ['src/INVOICE.cbl', 'src/DISCOUNT.cbl']);
    assert.equal(files[0].lines.get(58), 12);
    assert.equal(files[0].functions[1].name, '1000-READ');
    assert.equal(files[0].branches[1].taken, 24);
  });

  test('a last record without end_of_record is still returned', () => {
    const files = parseLcov(text(INVOICE, DISCOUNT.slice(0, -1)));
    assert.equal(files.length, 2);
    assert.equal(files[1].lines.get(16), 9);
  });

  test('records before the first SF are ignored', () => {
    const files = parseLcov(text(['DA:1,5', 'FN:1,ORPHAN', 'end_of_record'], DISCOUNT));
    assert.deepEqual(files.map((f) => f.path), ['src/DISCOUNT.cbl']);
    assert.equal(files[0].lines.has(1), false);
  });

  test('an empty text yields no files', () => {
    assert.deepEqual(parseLcov(''), []);
  });
});
