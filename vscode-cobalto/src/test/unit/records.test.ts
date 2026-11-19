// Unit tests for the reading of lldb's "memory read" output in
// src/dap/records.ts, the path used with an lldb-dap that has no readMemory
// request.

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { bytesOfMemoryRead } from '../../dap/records';

describe('bytesOfMemoryRead', () => {
  test('the bytes of one line, without its address', () => {
    assert.deepEqual(bytesOfMemoryRead('0xaaaaaabcfa20: 0x30 0x30 0x31 0x20\n'), [0x30, 0x30, 0x31, 0x20]);
  });

  test('several lines are read in order', () => {
    const output = '0x00001000: 0x41 0x42 0x43 0x44 0x45 0x46 0x47 0x48\n0x00001008: 0x49 0x4a\n';
    assert.deepEqual(bytesOfMemoryRead(output), [0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4a]);
  });

  test('an address that looks like a byte is not taken for one', () => {
    assert.deepEqual(bytesOfMemoryRead('0x10: 0xff 0x00\n'), [0xff, 0x00]);
  });

  test('lines that are not memory, such as an error, give no bytes', () => {
    assert.deepEqual(bytesOfMemoryRead('error: memory read failed for 0x0\n'), []);
    assert.deepEqual(bytesOfMemoryRead(''), []);
  });
});
