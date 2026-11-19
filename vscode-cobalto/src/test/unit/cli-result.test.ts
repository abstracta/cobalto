// Unit tests for src/cli-result.ts: reading how a run of the CLI ended.

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { stopReason, wroteResults } from '../../cli-result';

describe('wroteResults', () => {
  test('exit 0 (every case passed) wrote results', () => {
    assert.equal(wroteResults(0), true);
  });

  test('exit 1 (some case failed) wrote results', () => {
    assert.equal(wroteResults(1), true);
  });

  test('exit 2 (an error of the CLI) did not write results', () => {
    assert.equal(wroteResults(2), false);
  });

  test('a killed process (no exit code) did not write results', () => {
    assert.equal(wroteResults(null), false);
  });

  test('any other exit code did not write results', () => {
    assert.equal(wroteResults(127), false);
    assert.equal(wroteResults(-1), false);
  });
});

describe('stopReason', () => {
  test('the reason is the error line of the CLI when there is one', () => {
    const output = ['Compiling TSTINV', 'CBLT-E201: tests/INVOICE.cblt:14: unknown statement EXPCT', 'Nothing was run'].join('\n');
    assert.equal(stopReason(output), 'CBLT-E201: tests/INVOICE.cblt:14: unknown statement EXPCT');
  });

  test('several error lines are all kept, in order', () => {
    const output = ['CBLT-E201: tests/A.cblt:3: first', 'note', 'CBLT-E305: tests/B.cblt:9: second', 'CBLT-E201: tests/C.cblt:1: third'].join('\n');
    assert.equal(stopReason(output), ['CBLT-E201: tests/A.cblt:3: first', 'CBLT-E305: tests/B.cblt:9: second', 'CBLT-E201: tests/C.cblt:1: third'].join('\n'));
  });

  test('an error code in the middle of a line counts', () => {
    assert.equal(stopReason('step 1\nerror: CBLT-E410 the compiler was not found\nstep 3'), 'error: CBLT-E410 the compiler was not found');
  });

  test('a warning code is not an error line', () => {
    const output = ['CBLT-W301: tests/A.cblt:3: a warning', 'cobc: syntax error'].join('\n');
    assert.equal(stopReason(output), output);
  });

  test('without error lines the reason is the last five lines', () => {
    const lines = ['one', 'two', 'three', 'four', 'five', 'six', 'seven'];
    assert.equal(stopReason(lines.join('\n')), ['three', 'four', 'five', 'six', 'seven'].join('\n'));
  });

  test('a short output without error lines is returned whole', () => {
    assert.equal(stopReason('cobc: command not found\nexit 127'), 'cobc: command not found\nexit 127');
  });

  test('blank lines do not count among the last five', () => {
    const output = ['one', '', 'two', '   ', 'three', 'four', '', 'five', 'six', '', ''].join('\n');
    assert.equal(stopReason(output), ['two', 'three', 'four', 'five', 'six'].join('\n'));
  });

  test('CRLF output is split into lines', () => {
    assert.equal(stopReason('Compiling\r\nCBLT-E201: bad statement\r\nstopped\r\n'), 'CBLT-E201: bad statement');
  });

  test('an empty output gives an empty reason', () => {
    assert.equal(stopReason(''), '');
    assert.equal(stopReason('\n\n'), '');
  });
});
