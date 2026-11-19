// Unit tests for src/dap/layout.ts: formatting and encoding of COBOL fields,
// references with subscripts, the layout document and COBOL conditions.
// The bytes are written by hand following GnuCOBOL's encodings (on a
// little-endian machine); src/test/verify-layout.ts checks the same module
// against bytes written by a compiled program.

import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { after, before, describe, test } from 'node:test';
import {
  conditionNames, decimalToString, encodeValue, evalCondition, formatValue, Layout, LayoutItem, Located, looksLikeC,
  offsetOf, Operand, operandOf, parseDecimal, parseReference, readInt, Reference, rescale,
} from '../../dap/layout';
import { SUPPORTED_SCHEMA } from '../../dap/schema';

function item(partial: Partial<LayoutItem> & { kind: LayoutItem['kind']; size: number }): LayoutItem {
  return { name: 'WS-FIELD', level: 5, section: 'WORKING-STORAGE', pic: '', usage: 'DISPLAY', occurs: 0, redefines: null, digits: 0, scale: 0, signed: false, offset: 0, children: [], ...partial };
}

const ascii = (s: string): Buffer => Buffer.from(s, 'latin1');
const hex = (s: string): Buffer => Buffer.from(s.replace(/\s/g, ''), 'hex');

// The declarations the tests use, as the layout document describes them.
const DISPLAY_5 = item({ kind: 'display', pic: '9(5)', size: 5, digits: 5 });
const DISPLAY_5V2 = item({ kind: 'display', pic: '9(5)V99', size: 7, digits: 7, scale: 2 });
const DISPLAY_S5 = item({ kind: 'display', pic: 'S9(5)', size: 5, digits: 5, signed: true });
const DISPLAY_S5V2 = item({ kind: 'display', pic: 'S9(5)V99', size: 7, digits: 7, scale: 2, signed: true });
const DISPLAY_S3_SEPARATE = item({ kind: 'display', pic: 'S9(3)', size: 4, digits: 3, signed: true, sign_separate: true });
const COMP3_S5V2 = item({ kind: 'comp3', pic: 'S9(5)V99', usage: 'COMP-3', size: 4, digits: 7, scale: 2, signed: true });
const COMP3_S3 = item({ kind: 'comp3', pic: 'S9(3)', usage: 'COMP-3', size: 2, digits: 3, signed: true });
const COMP3_3 = item({ kind: 'comp3', pic: '9(3)', usage: 'COMP-3', size: 2, digits: 3 });
const COMP3_S4 = item({ kind: 'comp3', pic: 'S9(4)', usage: 'COMP-3', size: 3, digits: 4, signed: true });
const COMP_4 = item({ kind: 'binary', pic: '9(4)', usage: 'COMP', size: 2, digits: 4 });
const COMP_S9 = item({ kind: 'binary', pic: 'S9(9)', usage: 'COMP', size: 4, digits: 9, signed: true });
const COMP_S4V1 = item({ kind: 'binary', pic: 'S9(4)V9', usage: 'COMP', size: 2, digits: 5, scale: 1, signed: true });
const COMP5_4 = item({ kind: 'comp5', pic: '9(4)', usage: 'COMP-5', size: 2, digits: 4 });
const COMP5_S4 = item({ kind: 'comp5', pic: 'S9(4)', usage: 'COMP-5', size: 2, digits: 4, signed: true });
const ALNUM_6 = item({ kind: 'alnum', pic: 'X(6)', size: 6 });
const EDITED_6 = item({ kind: 'numedit', pic: 'ZZ9.99', size: 6 });
const GROUP_4 = item({ kind: 'group', size: 4 });
const INDEX = item({ kind: 'index', usage: 'INDEX', size: 4 });
const POINTER = item({ kind: 'pointer', usage: 'POINTER', size: 8 });
const COMP1 = item({ kind: 'float', usage: 'COMP-1', size: 4 });
const COMP2 = item({ kind: 'double', usage: 'COMP-2', size: 8 });

describe('formatValue: numeric DISPLAY', () => {
  test('an unsigned field shows its digits with the leading zeros', () => {
    assert.equal(formatValue(ascii('00042'), DISPLAY_5), '00042');
  });

  test('implied decimals get their decimal point', () => {
    assert.equal(formatValue(ascii('0012345'), DISPLAY_5V2), '00123.45');
  });

  test('a field with decimals only shows a zero before the point', () => {
    assert.equal(formatValue(ascii('25'), item({ kind: 'display', pic: 'V99', size: 2, digits: 2, scale: 2 })), '0.25');
  });

  test('a positive signed field is shown without a sign', () => {
    assert.equal(formatValue(ascii('00123'), DISPLAY_S5), '00123');
  });

  test('a negative signed field carries its sign in the last digit (GnuCOBOL overpunch)', () => {
    assert.equal(formatValue(ascii('0012s'), DISPLAY_S5), '-00123');
    assert.equal(formatValue(ascii('0012p'), DISPLAY_S5), '-00120');
  });

  test('a negative value with decimals shows sign and point', () => {
    assert.equal(formatValue(ascii('001234u'), DISPLAY_S5V2), '-00123.45');
  });

  test('the EBCDIC-style overpunch of a negative value (J to R and }) is read too', () => {
    assert.equal(formatValue(ascii('0012N'), DISPLAY_S5), '-00125');
    assert.equal(formatValue(ascii('0012}'), DISPLAY_S5), '-00120');
  });

  test('the EBCDIC-style overpunch of a positive value (A to I and {) is read too', () => {
    assert.equal(formatValue(ascii('0012E'), DISPLAY_S5), '00125');
    assert.equal(formatValue(ascii('0012{'), DISPLAY_S5), '00120');
  });

  test('a separate leading sign is read from the first byte', () => {
    assert.equal(formatValue(ascii('-007'), DISPLAY_S3_SEPARATE), '-007');
    assert.equal(formatValue(ascii('+007'), DISPLAY_S3_SEPARATE), '007');
  });

  test('a separate trailing sign is read from the last byte', () => {
    assert.equal(formatValue(ascii('012-'), DISPLAY_S3_SEPARATE), '-012');
    assert.equal(formatValue(ascii('012+'), DISPLAY_S3_SEPARATE), '012');
  });

  test('bytes that are not digits are shown as ?', () => {
    assert.equal(formatValue(ascii('12 4\0'), DISPLAY_5), '12?4?');
  });
});

describe('formatValue: COMP-3', () => {
  test('a positive packed value shows its digits', () => {
    assert.equal(formatValue(hex('12 3c'), COMP3_S3), '123');
  });

  test('the sign nibble D makes it negative', () => {
    assert.equal(formatValue(hex('12 3d'), COMP3_S3), '-123');
  });

  test('an unsigned packed value (sign nibble F) shows its digits', () => {
    assert.equal(formatValue(hex('04 2f'), COMP3_3), '042');
  });

  test('with an even number of digits the padding nibble is not shown', () => {
    assert.equal(formatValue(hex('01 23 4c'), COMP3_S4), '1234');
  });

  test('implied decimals get their decimal point', () => {
    assert.equal(formatValue(hex('00 12 34 5d'), COMP3_S5V2), '-00123.45');
  });
});

describe('formatValue: COMP and COMP-5', () => {
  test('COMP is read big-endian', () => {
    assert.equal(formatValue(hex('04 d2'), COMP_4), '1234');
  });

  test('COMP-5 is read in the native order of the machine', () => {
    assert.equal(formatValue(hex('d2 04'), COMP5_4), '1234');
  });

  test('the same bytes are a different number as COMP and as COMP-5', () => {
    assert.equal(formatValue(hex('00 01'), COMP_4), '0001');
    assert.equal(formatValue(hex('00 01'), COMP5_4), '0256');
  });

  test("a negative signed COMP is read as two's complement", () => {
    assert.equal(formatValue(hex('ff ff ff 9c'), COMP_S9), '-000000100');
  });

  test("a negative signed COMP-5 is read as two's complement", () => {
    assert.equal(formatValue(hex('fe ff'), COMP5_S4), '-0002');
  });

  test('an unsigned binary field with the high bit set is not negative', () => {
    assert.equal(formatValue(hex('ff ff'), COMP_4), '65535');
  });

  test('the value is padded with zeros to the digits of the PIC', () => {
    assert.equal(formatValue(hex('00 07'), COMP_4), '0007');
  });

  test('implied decimals get their decimal point', () => {
    assert.equal(formatValue(hex('ff 83'), COMP_S4V1), '-0012.5');
  });
});

describe('formatValue: text', () => {
  test('an alphanumeric field is shown in quotes with its trailing spaces', () => {
    assert.equal(formatValue(ascii('AB    '), ALNUM_6), '"AB    "');
  });

  test('control characters are shown as a dot', () => {
    assert.equal(formatValue(ascii('AB\x00\x01\x1f\x7f'), ALNUM_6), '"AB...."');
  });

  test('a quote and a backslash inside the text are escaped', () => {
    assert.equal(formatValue(ascii('a"b\\c '), ALNUM_6), '"a\\"b\\\\c "');
  });

  test('bytes above ASCII are read as Latin-1', () => {
    assert.equal(formatValue(Buffer.from([0x54, 0xdc, 0x52, 0x20, 0x20, 0x20]), ALNUM_6), '"TÜR   "');
  });

  test('an edited field is shown as the text it holds', () => {
    assert.equal(formatValue(ascii('  3.50'), EDITED_6), '"  3.50"');
  });

  test('a group is shown as the text of all its bytes', () => {
    assert.equal(formatValue(ascii('AB12'), GROUP_4), '"AB12"');
  });
});

describe('formatValue: other usages', () => {
  test('an index is shown as an integer', () => {
    assert.equal(formatValue(hex('03 00 00 00'), INDEX), '3');
  });

  test('a pointer is shown as a hexadecimal address of its full width', () => {
    assert.equal(formatValue(hex('10 20 00 00 00 00 00 00'), POINTER), '0x0000000000002010');
  });

  test('COMP-1 is shown as a floating point number', () => {
    const bytes = Buffer.alloc(4);
    bytes.writeFloatLE(2.5);
    assert.equal(formatValue(bytes, COMP1), '2.5');
  });

  test('COMP-2 is shown as a floating point number', () => {
    const bytes = Buffer.alloc(8);
    bytes.writeDoubleLE(-1234.5625);
    assert.equal(formatValue(bytes, COMP2), '-1234.5625');
  });
});

describe('formatValue: the buffer', () => {
  test('a buffer shorter than the field says how many bytes could be read', () => {
    assert.match(formatValue(ascii('12'), DISPLAY_5), /2 of 5 bytes/);
  });

  test('only the bytes of the field are read from a longer buffer', () => {
    assert.equal(formatValue(ascii('00042999'), DISPLAY_5), '00042');
    assert.equal(formatValue(ascii('AB    CD'), ALNUM_6), '"AB    "');
  });
});

describe('encodeValue: round trips', () => {
  const cases: { label: string; field: LayoutItem; text: string; bytes: Buffer; shown: string }[] = [
    { label: 'unsigned DISPLAY', field: DISPLAY_5, text: '42', bytes: ascii('00042'), shown: '00042' },
    { label: 'DISPLAY with decimals', field: DISPLAY_5V2, text: '123.45', bytes: ascii('0012345'), shown: '00123.45' },
    { label: 'signed DISPLAY, positive', field: DISPLAY_S5, text: '123', bytes: ascii('00123'), shown: '00123' },
    { label: 'signed DISPLAY, negative', field: DISPLAY_S5, text: '-123', bytes: ascii('0012s'), shown: '-00123' },
    { label: 'signed DISPLAY with decimals, negative', field: DISPLAY_S5V2, text: '-123.45', bytes: ascii('001234u'), shown: '-00123.45' },
    { label: 'signed COMP-3, positive', field: COMP3_S3, text: '42', bytes: hex('04 2c'), shown: '042' },
    { label: 'signed COMP-3 with decimals, negative', field: COMP3_S5V2, text: '-123.45', bytes: hex('00 12 34 5d'), shown: '-00123.45' },
    { label: 'unsigned COMP-3', field: COMP3_3, text: '42', bytes: hex('04 2f'), shown: '042' },
    { label: 'COMP-3 with an even number of digits', field: COMP3_S4, text: '1234', bytes: hex('01 23 4c'), shown: '1234' },
    { label: 'unsigned COMP', field: COMP_4, text: '1234', bytes: hex('04 d2'), shown: '1234' },
    { label: 'signed COMP, negative', field: COMP_S9, text: '-100', bytes: hex('ff ff ff 9c'), shown: '-000000100' },
    { label: 'signed COMP with decimals, negative', field: COMP_S4V1, text: '-12.5', bytes: hex('ff 83'), shown: '-0012.5' },
    { label: 'unsigned COMP-5', field: COMP5_4, text: '1234', bytes: hex('d2 04'), shown: '1234' },
    { label: 'signed COMP-5, negative', field: COMP5_S4, text: '-2', bytes: hex('fe ff'), shown: '-0002' },
    { label: 'alphanumeric', field: ALNUM_6, text: 'AB', bytes: ascii('AB    '), shown: '"AB    "' },
    { label: 'edited', field: EDITED_6, text: '  3.50', bytes: ascii('  3.50'), shown: '"  3.50"' },
    { label: 'group', field: GROUP_4, text: 'AB12', bytes: ascii('AB12'), shown: '"AB12"' },
    { label: 'index', field: INDEX, text: '3', bytes: hex('03 00 00 00'), shown: '3' },
    { label: 'pointer', field: POINTER, text: '0x2010', bytes: hex('10 20 00 00 00 00 00 00'), shown: '0x0000000000002010' },
    { label: 'COMP-1', field: COMP1, text: '2.5', bytes: hex('00 00 20 40'), shown: '2.5' },
    { label: 'COMP-2', field: COMP2, text: '1.5', bytes: hex('00 00 00 00 00 00 f8 3f'), shown: '1.5' },
  ];
  for (const c of cases) {
    test(`${c.label}: ${JSON.stringify(c.text)} is stored in the encoding of the field and read back as ${c.shown}`, () => {
      const encoded = encodeValue(c.text, c.field);
      assert.equal(encoded.toString('hex'), c.bytes.toString('hex'));
      assert.equal(formatValue(encoded, c.field), c.shown);
    });
  }

  test('the text formatValue shows for a numeric field encodes to the same bytes', () => {
    for (const [bytes, field] of [[ascii('001234u'), DISPLAY_S5V2], [hex('00 12 34 5d'), COMP3_S5V2], [hex('ff ff ff 9c'), COMP_S9], [hex('fe ff'), COMP5_S4]] as const) {
      assert.equal(encodeValue(formatValue(bytes, field), field).toString('hex'), bytes.toString('hex'));
    }
  });

  test('an alphanumeric value with a quote or a backslash survives the round trip', () => {
    const bytes = ascii('a"b\\c ');
    assert.equal(formatValue(bytes, ALNUM_6), '"a\\"b\\\\c "');
    assert.equal(encodeValue(formatValue(bytes, ALNUM_6), ALNUM_6).toString('latin1'), 'a"b\\c ');
  });
});

describe('encodeValue: numbers', () => {
  test('a value with fewer decimals than the field is completed with zeros', () => {
    assert.equal(encodeValue('1.5', DISPLAY_5V2).toString('latin1'), '0000150');
  });

  test('decimals beyond those of the field are truncated, like a MOVE', () => {
    assert.equal(encodeValue('1.999', DISPLAY_5V2).toString('latin1'), '0000199');
  });

  test('an explicit plus sign is accepted', () => {
    assert.equal(encodeValue('+7', DISPLAY_5).toString('latin1'), '00007');
  });

  test('spaces around the number are ignored', () => {
    assert.equal(encodeValue('  42 ', DISPLAY_5).toString('latin1'), '00042');
  });

  test('a separate trailing sign stays trailing', () => {
    assert.equal(encodeValue('-5', DISPLAY_S3_SEPARATE, ascii('012+')).toString('latin1'), '005-');
  });

  test('a separate leading sign stays leading', () => {
    assert.equal(encodeValue('-5', DISPLAY_S3_SEPARATE, ascii('+012')).toString('latin1'), '-005');
  });

  test('a positive value writes the plus of a separate sign', () => {
    assert.equal(encodeValue('5', DISPLAY_S3_SEPARATE, ascii('-012')).toString('latin1'), '+005');
    assert.equal(encodeValue('5', DISPLAY_S3_SEPARATE, ascii('012-')).toString('latin1'), '005+');
  });
});

describe('encodeValue: rejections', () => {
  test('a number with more integer digits than the PIC is rejected', () => {
    assert.throws(() => encodeValue('100000', DISPLAY_5), /does not fit in 5 digits/);
  });

  test('the decimals of the field count against its digits', () => {
    assert.throws(() => encodeValue('100000', DISPLAY_5V2), /does not fit/);
    assert.equal(encodeValue('99999.99', DISPLAY_5V2).toString('latin1'), '9999999');
  });

  test('a number too long for a COMP-3 field is rejected', () => {
    assert.throws(() => encodeValue('1000', COMP3_S3), /does not fit in 3 digits/);
  });

  test('a number too long for the PIC of a binary field is rejected', () => {
    assert.throws(() => encodeValue('10000', COMP_4), /does not fit in 4 digits/);
    assert.throws(() => encodeValue('-10000', COMP5_S4), /does not fit in 4 digits/);
  });

  test('text that is not a decimal number is rejected by a numeric field', () => {
    for (const text of ['hello', '', '12abc', '1e3', '1,5', '.']) {
      assert.throws(() => encodeValue(text, DISPLAY_5), /is not a number/, JSON.stringify(text));
    }
  });

  test('text is rejected by packed, binary and floating point fields as well', () => {
    for (const field of [COMP3_S3, COMP_4, COMP5_S4, COMP2]) {
      assert.throws(() => encodeValue('hello', field), /is not a number/, field.usage);
    }
  });

  test('a negative value is rejected by an unsigned field', () => {
    for (const field of [DISPLAY_5, COMP3_3, COMP_4, COMP5_4]) {
      assert.throws(() => encodeValue('-1', field), /is unsigned/, field.usage);
    }
  });

  test('the rejection of a negative value names the field', () => {
    assert.throws(() => encodeValue('-1', { ...DISPLAY_5, name: 'WS-COUNT' }), /WS-COUNT/);
  });
});

describe('encodeValue: text', () => {
  test('a shorter text is padded with spaces', () => {
    assert.equal(encodeValue('AB', ALNUM_6).toString('latin1'), 'AB    ');
  });

  test('double quotes around the text are not part of it', () => {
    assert.equal(encodeValue('"AB"', ALNUM_6).toString('latin1'), 'AB    ');
  });

  test('single quotes around the text are not part of it', () => {
    assert.equal(encodeValue("'AB'", ALNUM_6).toString('latin1'), 'AB    ');
  });

  test('spaces inside the quotes are kept', () => {
    assert.equal(encodeValue('" AB "', ALNUM_6).toString('latin1'), ' AB   ');
  });

  test('a text longer than the field is cut at its size, like a MOVE', () => {
    assert.equal(encodeValue('ABCDEFGHIJ', ALNUM_6).toString('latin1'), 'ABCDEF');
  });

  test('characters above ASCII are stored as Latin-1', () => {
    assert.deepEqual([...encodeValue('TÜR', ALNUM_6)], [0x54, 0xdc, 0x52, 0x20, 0x20, 0x20]);
  });

  test('a number given to an alphanumeric field is stored as its characters', () => {
    assert.equal(encodeValue('42', ALNUM_6).toString('latin1'), '42    ');
  });
});

describe('decimal helpers', () => {
  test('parseDecimal reads the sign and counts the decimals', () => {
    assert.deepEqual(parseDecimal('-12.50'), { value: -1250n, scale: 2 });
  });

  test('parseDecimal accepts a number without integer part or without decimals', () => {
    assert.deepEqual(parseDecimal('.5'), { value: 5n, scale: 1 });
    assert.deepEqual(parseDecimal('7.'), { value: 7n, scale: 0 });
    assert.deepEqual(parseDecimal('007'), { value: 7n, scale: 0 });
  });

  test('parseDecimal rejects what is not a decimal number', () => {
    for (const text of ['abc', '', '.', '1e3', '1.2.3', '--1']) {
      assert.equal(parseDecimal(text), undefined, JSON.stringify(text));
    }
  });

  test('rescale adds decimal places without changing the value', () => {
    assert.equal(rescale({ value: 125n, scale: 1 }, 3), 12500n);
  });

  test('rescale drops decimal places by truncating, not rounding', () => {
    assert.equal(rescale({ value: 12567n, scale: 3 }, 1), 125n);
    assert.equal(rescale({ value: -12567n, scale: 3 }, 1), -125n);
  });

  test('decimalToString writes sign, integer part and every decimal', () => {
    assert.equal(decimalToString({ value: -1250n, scale: 2 }), '-12.50');
    assert.equal(decimalToString({ value: 5n, scale: 0 }), '5');
    assert.equal(decimalToString({ value: 5n, scale: 2 }), '0.05');
  });

  test('readInt reads the same bytes in either byte order', () => {
    assert.equal(readInt(hex('01 02'), false, false), 0x0102n);
    assert.equal(readInt(hex('01 02'), false, true), 0x0201n);
  });

  test('readInt takes the high bit as the sign only when the field is signed', () => {
    assert.equal(readInt(hex('ff fe'), true, false), -2n);
    assert.equal(readInt(hex('ff fe'), false, false), 65534n);
  });
});

describe('parseReference', () => {
  test('a plain name has no subscripts', () => {
    assert.deepEqual(parseReference('WS-AMOUNT'), { name: 'WS-AMOUNT', subscripts: [] });
  });

  test('the name is given in uppercase', () => {
    assert.equal(parseReference('ws-Amount')?.name, 'WS-AMOUNT');
  });

  test('spaces around the reference are ignored', () => {
    assert.deepEqual(parseReference('  WS-AMOUNT  '), { name: 'WS-AMOUNT', subscripts: [] });
  });

  test('a subscript in parentheses is read as a number', () => {
    assert.deepEqual(parseReference('WS-T-QTY(2)'), { name: 'WS-T-QTY', subscripts: [2] });
  });

  test('several subscripts may be separated by commas or by spaces', () => {
    assert.deepEqual(parseReference('WS-CELL(1, 2)')?.subscripts, [1, 2]);
    assert.deepEqual(parseReference('WS-CELL(1 2)')?.subscripts, [1, 2]);
    assert.deepEqual(parseReference('WS-CELL(1,2,3)')?.subscripts, [1, 2, 3]);
  });

  test('a space may separate the name from its subscripts', () => {
    assert.deepEqual(parseReference('WS-CELL (1, 2)'), { name: 'WS-CELL', subscripts: [1, 2] });
  });

  test('a name may start with a digit as long as it has a letter', () => {
    assert.equal(parseReference('1ST-AMOUNT')?.name, '1ST-AMOUNT');
  });

  test('a number is not a reference', () => {
    assert.equal(parseReference('1234'), undefined);
  });

  test('a C expression is not a reference', () => {
    for (const text of ['b_32[0]', 'f_18.data', '*b_9', 'WS-A + 1']) {
      assert.equal(parseReference(text), undefined, text);
    }
  });

  test('a subscript that is not a number is not accepted', () => {
    assert.equal(parseReference('WS-CELL(IDX)'), undefined);
    assert.equal(parseReference('WS-CELL()'), undefined);
  });

  test('an unbalanced parenthesis is not accepted', () => {
    assert.equal(parseReference('WS-CELL(1'), undefined);
    assert.equal(parseReference('WS-CELL 1)'), undefined);
  });
});

describe('offsetOf', () => {
  // 01 WS-YEAR.  05 WS-MONTH OCCURS 2.  10 WS-DAY OCCURS 3.  15 WS-TAG PIC X(8).  15 WS-VAL PIC 9(4).
  const month = item({ name: 'WS-MONTH', kind: 'group', size: 36, occurs: 2, offset: 10 });
  const day = item({ name: 'WS-DAY', kind: 'group', size: 12, occurs: 3, offset: 10 });
  const val = item({ name: 'WS-VAL', kind: 'display', size: 4, digits: 4, offset: 18 });
  const year = item({ name: 'WS-YEAR', kind: 'group', level: 1, size: 82 });
  const inTable: Located = { root: year, item: val, dims: [month, day] };
  const plain: Located = { root: year, item: item({ name: 'WS-HEAD', kind: 'alnum', size: 10, offset: 0 }), dims: [] };

  test('a field outside any OCCURS is at its own offset', () => {
    assert.deepEqual(offsetOf({ ...plain, item: { ...plain.item, offset: 7 } }, []), { offset: 7 });
  });

  test('the first occurrence is at the offset of the layout', () => {
    assert.equal(offsetOf(inTable, [1, 1]).offset, 18);
  });

  test('each subscript advances by the size of one occurrence of its level', () => {
    assert.equal(offsetOf(inTable, [1, 3]).offset, 18 + 2 * 12);
    assert.equal(offsetOf(inTable, [2, 1]).offset, 18 + 36);
    assert.equal(offsetOf(inTable, [2, 3]).offset, 18 + 36 + 2 * 12);
  });

  test('the subscripts apply from the outermost OCCURS inwards', () => {
    assert.notEqual(offsetOf(inTable, [2, 1]).offset, offsetOf(inTable, [1, 2]).offset);
  });

  test('a subscript left out means the first occurrence', () => {
    assert.equal(offsetOf(inTable, []).offset, 18);
    assert.equal(offsetOf(inTable, [2]).offset, 18 + 36);
  });

  test('an item with its own OCCURS takes a subscript for itself', () => {
    const qty = item({ name: 'WS-QTY', kind: 'display', size: 3, digits: 3, occurs: 5, offset: 4 });
    assert.equal(offsetOf({ root: year, item: qty, dims: [qty] }, [4]).offset, 4 + 3 * 3);
  });

  test('more subscripts than OCCURS levels is reported as an error', () => {
    const result = offsetOf(inTable, [1, 2, 3]);
    assert.ok(result.error);
    assert.match(result.error, /WS-VAL/);
  });

  test('a subscript on a field without OCCURS is reported as an error', () => {
    assert.ok(offsetOf(plain, [1]).error);
  });

  test('a subscript above the number of occurrences is out of range', () => {
    assert.throws(() => offsetOf(inTable, [3, 1]), /out of range 1\.\.2/);
    assert.throws(() => offsetOf(inTable, [1, 4]), /out of range 1\.\.3/);
  });

  test('subscript zero is out of range', () => {
    assert.throws(() => offsetOf(inTable, [0, 1]), /out of range/);
  });
});

// The layout document of two programs. ORDERS has a record with a table, a
// name declared in two records, a record cobc described inconsistently, a
// LINKAGE parameter and the record of a file (without section).
const ORDER_RECORD = item({
  name: 'WS-ORDER', level: 1, kind: 'group', size: 26,
  children: [
    item({ name: 'WS-ORDER-ID', kind: 'display', pic: '9(4)', size: 4, digits: 4, offset: 0 }),
    item({
      name: 'WS-LINE', kind: 'group', size: 6, occurs: 3, offset: 4,
      children: [
        item({ name: 'WS-L-QTY', level: 10, kind: 'display', pic: '9(2)', size: 2, digits: 2, offset: 4 }),
        item({ name: 'WS-L-PRICE', level: 10, kind: 'comp3', pic: 'S9(5)V99', usage: 'COMP-3', size: 4, digits: 7, scale: 2, signed: true, offset: 6 }),
      ],
    }),
    item({ name: 'WS-STATUS', kind: 'alnum', pic: 'X(4)', size: 4, offset: 22 }),
  ],
});

const LAYOUT_DOCUMENT = {
  schema: SUPPORTED_SCHEMA,
  cobalto: '0.7.0',
  suite: 'TSTORD',
  programs: {
    ORDERS: {
      source: 'src/ORDERS.cbl',
      warnings: [],
      items: [
        { ...item({ name: 'WS-BROKEN', level: 1, kind: 'group', size: 8, children: [item({ name: 'WS-STATUS', kind: 'alnum', size: 2 }), item({ name: 'WS-ONLY-BROKEN', kind: 'alnum', size: 6, offset: 2 })] }), unreliable: true },
        ORDER_RECORD,
        item({ name: 'WS-AUDIT', level: 1, kind: 'group', size: 9, children: [item({ name: 'WS-ORDER-ID', kind: 'display', pic: '9(9)', size: 9, digits: 9 })] }),
        item({ name: 'WS-TOTAL', level: 1, kind: 'display', pic: 'S9(7)V99', size: 9, digits: 9, scale: 2, signed: true }),
        item({ name: 'LN-AMOUNT', level: 1, section: 'LINKAGE', kind: 'display', pic: '9(7)V99', size: 9, digits: 9, scale: 2 }),
        { ...item({ name: 'ORDER-REC', level: 1, kind: 'alnum', pic: 'X(26)', size: 26 }), section: null },
      ],
    },
    DISCOUNT: {
      source: 'src/DISCOUNT.cbl',
      warnings: [],
      items: [item({ name: 'WS-TOTAL', level: 1, kind: 'comp3', pic: 'S9(5)', usage: 'COMP-3', size: 3, digits: 5, signed: true })],
    },
  },
};

/** WS-ORDER in memory: order 42, lines (2 x 150.00), (10 x -12.50), (0 x 0.00), status OPEN. */
const ORDER_BYTES = Buffer.concat([
  ascii('0042'),
  ascii('02'), hex('00 15 00 0c'),
  ascii('10'), hex('00 01 25 0d'),
  ascii('00'), hex('00 00 00 0c'),
  ascii('OPEN'),
]);

describe('Layout', () => {
  let tmp = '';
  let count = 0;
  let layout: Layout;

  function write(content: string): string {
    const file = path.join(tmp, `suite-${++count}.layout.json`);
    fs.writeFileSync(file, content);
    return file;
  }

  before(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cobalto-layout-unit-'));
    const loaded = Layout.load(write(JSON.stringify(LAYOUT_DOCUMENT)));
    assert.ok(loaded, 'the layout should load');
    layout = loaded;
  });

  after(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  test('a program is found by name, whatever the case', () => {
    assert.equal(layout.program('orders')?.source, 'src/ORDERS.cbl');
    assert.equal(layout.program('DISCOUNT')?.source, 'src/DISCOUNT.cbl');
  });

  test('a program that is not in the document, or no name, gives nothing', () => {
    assert.equal(layout.program('PREMIUM'), undefined);
    assert.equal(layout.program(undefined), undefined);
  });

  test('a subordinate field is found with the record it belongs to', () => {
    const loc = layout.find('ORDERS', 'WS-L-PRICE');
    assert.equal(loc?.item.name, 'WS-L-PRICE');
    assert.equal(loc?.root.name, 'WS-ORDER');
  });

  test('a field is found by name, whatever the case', () => {
    assert.equal(layout.find('orders', 'ws-l-qty')?.item.name, 'WS-L-QTY');
  });

  test('a field inside a table knows the OCCURS that contains it', () => {
    assert.deepEqual(layout.find('ORDERS', 'WS-L-QTY')?.dims.map((d) => d.name), ['WS-LINE']);
  });

  test('the item that declares the OCCURS is its own dimension', () => {
    assert.deepEqual(layout.find('ORDERS', 'WS-LINE')?.dims.map((d) => d.name), ['WS-LINE']);
  });

  test('a field outside any table has no dimensions', () => {
    assert.deepEqual(layout.find('ORDERS', 'WS-ORDER')?.dims, []);
    assert.deepEqual(layout.find('ORDERS', 'WS-TOTAL')?.dims, []);
  });

  test('a name declared in two records gives the first declared', () => {
    assert.equal(layout.find('ORDERS', 'WS-ORDER-ID')?.root.name, 'WS-ORDER');
  });

  test('each program has its own fields', () => {
    assert.equal(layout.find('ORDERS', 'WS-TOTAL')?.item.kind, 'display');
    assert.equal(layout.find('DISCOUNT', 'WS-TOTAL')?.item.kind, 'comp3');
    assert.equal(layout.find('DISCOUNT', 'WS-ORDER'), undefined);
  });

  test('a name that is not in the program is not found', () => {
    assert.equal(layout.find('ORDERS', 'WS-MISSING'), undefined);
    assert.equal(layout.find('PREMIUM', 'WS-ORDER'), undefined);
  });

  test('the fields of an unreliable record are skipped in favour of a reliable one', () => {
    assert.equal(layout.find('ORDERS', 'WS-STATUS')?.root.name, 'WS-ORDER');
  });

  test('a field that only exists in an unreliable record is not found', () => {
    assert.equal(layout.find('ORDERS', 'WS-ONLY-BROKEN'), undefined);
  });

  test('a record is found by its name', () => {
    assert.equal(layout.root('ORDERS', 'ws-order')?.size, 26);
  });

  test('a subordinate field is not a record', () => {
    assert.equal(layout.root('ORDERS', 'WS-STATUS'), undefined);
  });

  test('an unreliable record is not returned', () => {
    assert.equal(layout.root('ORDERS', 'WS-BROKEN'), undefined);
  });

  test('a record can be asked for in given sections only', () => {
    assert.equal(layout.root('ORDERS', 'LN-AMOUNT', ['LINKAGE'])?.name, 'LN-AMOUNT');
    assert.equal(layout.root('ORDERS', 'LN-AMOUNT', ['WORKING-STORAGE', 'LOCAL-STORAGE']), undefined);
  });

  test('a record without a section belongs to the FILE section', () => {
    assert.equal(layout.root('ORDERS', 'ORDER-REC', ['FILE'])?.name, 'ORDER-REC');
    assert.equal(layout.root('ORDERS', 'ORDER-REC', ['WORKING-STORAGE']), undefined);
  });

  test('an occurrence of a table is read from the bytes of its record', () => {
    const loc = layout.find('ORDERS', 'WS-L-PRICE')!;
    const value = (line: number): string => {
      const { offset } = offsetOf(loc, [line]);
      return formatValue(ORDER_BYTES.subarray(offset, offset + loc.item.size), loc.item);
    };
    assert.deepEqual([value(1), value(2), value(3)], ['00150.00', '-00012.50', '00000.00']);
  });

  test('a COBOL condition is evaluated against the bytes of a record', () => {
    const resolve = (ref: Reference): Operand | undefined => {
      const loc = layout.find('ORDERS', ref.name);
      if (!loc) {
        return undefined;
      }
      const { offset } = offsetOf(loc, ref.subscripts);
      return operandOf(ORDER_BYTES.subarray(offset, offset + loc.item.size), loc.item);
    };
    assert.equal(evalCondition('WS-ORDER-ID = 42 AND WS-L-QTY(2) = 10 AND WS-L-PRICE(2) < 0 AND WS-STATUS = "OPEN"', resolve), true);
    assert.equal(evalCondition('WS-L-PRICE(1) < 150 OR WS-STATUS = "DONE"', resolve), false);
  });

  test('a file without the schema field (before 0.7.0) is read', () => {
    const { schema: _schema, cobalto: _cobalto, ...older } = LAYOUT_DOCUMENT;
    assert.equal(Layout.load(write(JSON.stringify(older)))?.find('ORDERS', 'WS-L-QTY')?.item.size, 2);
  });

  test('a file with a newer schema is not used and the reason is logged', () => {
    const file = write(JSON.stringify({ ...LAYOUT_DOCUMENT, schema: SUPPORTED_SCHEMA + 1, cobalto: '9.1.0' }));
    const log: string[] = [];
    assert.equal(Layout.load(file, (s) => log.push(s)), undefined);
    assert.equal(log.length, 1);
    assert.ok(log[0].includes(file));
    assert.ok(log[0].includes('9.1.0'));
  });

  test('a missing file gives no layout and says so in the log', () => {
    const log: string[] = [];
    assert.equal(Layout.load(path.join(tmp, 'does-not-exist.layout.json'), (s) => log.push(s)), undefined);
    assert.equal(log.length, 1);
  });

  test('a file that is not JSON gives no layout', () => {
    assert.equal(Layout.load(write('{"schema": 1, "programs": {')), undefined);
  });
});

// The fields a condition can name in the tests below.
const FIELDS: Record<string, Operand> = {
  'WS-QTY': { kind: 'number', value: { value: 9n, scale: 0 } },
  'WS-NET': { kind: 'number', value: { value: 160000n, scale: 2 } },
  'WS-BALANCE': { kind: 'number', value: { value: -500n, scale: 2 } },
  'WS-CATEGORY': { kind: 'text', value: 'PREMIUM   ' },
  'WS-CODE': { kind: 'text', value: '9   ' },
  'WS-MSG': { kind: 'text', value: 'NOT FOUND AND GONE' },
};

/** WS-ROW(i) is 10 * i and WS-CELL(i j) is 10 * i + j; any other name comes from FIELDS. */
function resolve(ref: Reference): Operand | undefined {
  if (ref.name === 'WS-ROW' && ref.subscripts.length === 1) {
    return { kind: 'number', value: { value: BigInt(ref.subscripts[0] * 10), scale: 0 } };
  }
  if (ref.name === 'WS-CELL' && ref.subscripts.length === 2) {
    return { kind: 'number', value: { value: BigInt(ref.subscripts[0] * 10 + ref.subscripts[1]), scale: 0 } };
  }
  return ref.subscripts.length ? undefined : FIELDS[ref.name];
}

const holds = (condition: string): boolean => evalCondition(condition, resolve);

describe('evalCondition: relations', () => {
  const symbols: [string, string, string][] = [
    ['=', 'WS-QTY = 9', 'WS-QTY = 8'],
    ['<>', 'WS-QTY <> 8', 'WS-QTY <> 9'],
    ['>', 'WS-QTY > 8', 'WS-QTY > 9'],
    ['<', 'WS-QTY < 10', 'WS-QTY < 9'],
    ['>=', 'WS-QTY >= 9', 'WS-QTY >= 10'],
    ['<=', 'WS-QTY <= 9', 'WS-QTY <= 8'],
  ];
  for (const [symbol, yes, no] of symbols) {
    test(`${symbol} compares the two operands (WS-QTY is 9: "${yes}" holds, "${no}" does not)`, () => {
      assert.equal(holds(yes), true);
      assert.equal(holds(no), false);
    });
  }

  const words: [string, string][] = [
    ['WS-QTY EQUAL TO 9', 'WS-QTY EQUAL TO 8'],
    ['WS-QTY EQUAL 9', 'WS-QTY EQUAL 8'],
    ['WS-QTY IS EQUAL TO 9', 'WS-QTY IS EQUAL TO 8'],
    ['WS-QTY EQUALS 9', 'WS-QTY EQUALS 8'],
    ['WS-QTY GREATER THAN 8', 'WS-QTY GREATER THAN 9'],
    ['WS-QTY IS GREATER THAN 8', 'WS-QTY IS GREATER THAN 9'],
    ['WS-QTY GREATER 8', 'WS-QTY GREATER 9'],
    ['WS-QTY LESS THAN 10', 'WS-QTY LESS THAN 9'],
    ['WS-QTY GREATER THAN OR EQUAL TO 9', 'WS-QTY GREATER THAN OR EQUAL TO 10'],
    ['WS-QTY LESS THAN OR EQUAL TO 9', 'WS-QTY LESS THAN OR EQUAL TO 8'],
    ['WS-QTY NOT EQUAL TO 8', 'WS-QTY NOT EQUAL TO 9'],
    ['WS-QTY IS NOT EQUAL TO 8', 'WS-QTY IS NOT EQUAL TO 9'],
    ['WS-QTY NOT GREATER THAN 9', 'WS-QTY NOT GREATER THAN 8'],
    ['WS-QTY NOT LESS THAN 9', 'WS-QTY NOT LESS THAN 10'],
  ];
  for (const [yes, no] of words) {
    test(`the relation in words "${yes.replace(/^WS-QTY | \d+$/g, '')}" is understood`, () => {
      assert.equal(holds(yes), true);
      assert.equal(holds(no), false);
    });
  }

  test('the C spellings != and == are accepted', () => {
    assert.equal(holds('WS-QTY != 8'), true);
    assert.equal(holds('WS-QTY == 9'), true);
    assert.equal(holds('WS-QTY == 8'), false);
  });

  test('spaces around a symbol are optional', () => {
    assert.equal(holds('WS-QTY=9'), true);
    assert.equal(holds('WS-QTY>=10'), false);
  });

  test('a literal may be on the left and a field on either side', () => {
    assert.equal(holds('1000 < WS-NET'), true);
    assert.equal(holds('WS-NET > WS-QTY'), true);
    assert.equal(holds('WS-QTY > WS-NET'), false);
  });

  test('a symbol after NOT or IS is understood (WS-QTY is 9)', () => {
    assert.equal(holds('WS-QTY NOT = 1'), true);
    assert.equal(holds('WS-QTY NOT = 9'), false);
    assert.equal(holds('WS-QTY IS = 9'), true);
    assert.equal(holds('WS-QTY IS NOT > 8'), false);
    assert.equal(holds('WS-QTY NOT < 9'), true);
  });
});

describe('evalCondition: numbers and text', () => {
  test('numbers compare by value, whatever their decimals', () => {
    assert.equal(holds('WS-NET = 1600'), true);
    assert.equal(holds('WS-NET = 1600.0'), true);
    assert.equal(holds('WS-NET = 1600.00'), true);
    assert.equal(holds('WS-NET = 1600.01'), false);
    assert.equal(holds('WS-NET < 1600.01'), true);
  });

  test('leading zeros of a literal do not change its value', () => {
    assert.equal(holds('WS-QTY = 009'), true);
  });

  test('negative values and literals keep their sign', () => {
    assert.equal(holds('WS-BALANCE < 0'), true);
    assert.equal(holds('WS-BALANCE = -5'), true);
    assert.equal(holds('WS-BALANCE > -5.01'), true);
    assert.equal(holds('WS-BALANCE = 5'), false);
  });

  test('a text equals a shorter literal padded with spaces', () => {
    assert.equal(holds("WS-CATEGORY = 'PREMIUM'"), true);
    assert.equal(holds('WS-CATEGORY = "PREMIUM   "'), true);
    assert.equal(holds('WS-CATEGORY = "PREMIUM      "'), true);
  });

  test('a text differs from a literal with other characters', () => {
    assert.equal(holds("WS-CATEGORY = 'PREMIUN'"), false);
    assert.equal(holds("WS-CATEGORY <> 'BASIC'"), true);
    assert.equal(holds("WS-CATEGORY = 'PREM'"), false);
  });

  test('text comparison tells uppercase from lowercase', () => {
    assert.equal(holds("WS-CATEGORY = 'premium'"), false);
  });

  test('texts are ordered character by character', () => {
    assert.equal(holds("WS-CATEGORY > 'BASIC'"), true);
    assert.equal(holds("WS-CATEGORY < 'STANDARD'"), true);
  });

  test('numbers are ordered by value where texts are ordered by their characters', () => {
    assert.equal(holds('WS-QTY < 10'), true);
    assert.equal(holds('WS-CODE < "10"'), false);
  });

  test('keywords and symbols inside a literal are text', () => {
    assert.equal(holds('WS-MSG = "NOT FOUND AND GONE"'), true);
    assert.equal(holds("WS-MSG = 'NOT FOUND OR GONE'"), false);
    assert.equal(holds('WS-MSG <> "A = B (C)"'), true);
  });
});

describe('evalCondition: AND, OR, NOT and parentheses', () => {
  test('AND holds only when both sides hold', () => {
    assert.equal(holds('WS-QTY = 9 AND WS-NET > 1000'), true);
    assert.equal(holds('WS-QTY = 9 AND WS-NET > 2000'), false);
    assert.equal(holds('WS-QTY = 1 AND WS-NET > 1000'), false);
  });

  test('OR holds when either side holds', () => {
    assert.equal(holds('WS-QTY = 1 OR WS-NET > 1000'), true);
    assert.equal(holds('WS-QTY = 9 OR WS-NET > 2000'), true);
    assert.equal(holds('WS-QTY = 1 OR WS-NET > 2000'), false);
  });

  test('AND binds tighter than OR', () => {
    assert.equal(holds('WS-QTY = 9 OR WS-QTY > 0 AND WS-NET > 2000'), true);
    assert.equal(holds('WS-NET > 2000 AND WS-QTY > 0 OR WS-QTY = 9'), true);
  });

  test('parentheses change the grouping', () => {
    assert.equal(holds('(WS-QTY = 9 OR WS-QTY > 0) AND WS-NET > 2000'), false);
  });

  test('NOT negates the comparison that follows', () => {
    assert.equal(holds('NOT WS-QTY = 1'), true);
    assert.equal(holds('NOT WS-QTY = 9'), false);
  });

  test('NOT negates a whole parenthesis', () => {
    assert.equal(holds('NOT (WS-QTY = 9 OR WS-QTY = 1)'), false);
    assert.equal(holds('NOT (WS-QTY = 9 AND WS-QTY = 1)'), true);
  });

  test('NOT binds tighter than AND', () => {
    assert.equal(holds('NOT WS-QTY = 1 AND WS-QTY = 1'), false);
  });

  test('a chain of three conditions is evaluated whole', () => {
    assert.equal(holds('WS-QTY = 9 AND WS-NET > 1000 AND WS-CATEGORY = "PREMIUM"'), true);
    assert.equal(holds('WS-QTY = 9 AND WS-NET > 1000 AND WS-CATEGORY = "BASIC"'), false);
    assert.equal(holds('WS-QTY = 1 OR WS-NET > 2000 OR WS-CATEGORY = "PREMIUM"'), true);
  });

  test('nested parentheses are accepted', () => {
    assert.equal(holds('((WS-QTY = 9) AND (WS-NET > 1000 OR (WS-QTY = 1)))'), true);
  });

  test('names and keywords may be written in lowercase', () => {
    assert.equal(holds('ws-qty = 9 and not ws-net is less than 1000 or ws-qty = 1'), true);
  });
});

describe('evalCondition: subscripts', () => {
  test('a subscript reaches the resolver with the name', () => {
    const seen: Reference[] = [];
    evalCondition('WS-ROW(2) = 20', (ref) => {
      seen.push(ref);
      return resolve(ref);
    });
    assert.deepEqual(seen, [{ name: 'WS-ROW', subscripts: [2] }]);
  });

  test('a field with a subscript is compared by the value of that occurrence', () => {
    assert.equal(holds('WS-ROW(2) = 20'), true);
    assert.equal(holds('WS-ROW(3) = 20'), false);
    assert.equal(holds('WS-ROW (2) < WS-ROW (3)'), true);
  });

  test('two subscripts separated by a space are both used', () => {
    assert.equal(holds('WS-CELL(2 3) = 23'), true);
  });

  test('a name without subscripts reaches the resolver with none', () => {
    const seen: Reference[] = [];
    evalCondition('WS-QTY = 9', (ref) => {
      seen.push(ref);
      return resolve(ref);
    });
    assert.deepEqual(seen, [{ name: 'WS-QTY', subscripts: [] }]);
  });

  test('two subscripts separated by a comma are understood, as parseReference does', () => {
    assert.equal(holds('WS-CELL(2, 3) = 23'), true);
    assert.equal(holds('WS-CELL(2,3) = 32'), false);
    assert.deepEqual(conditionNames('WS-CELL(2, 3) = 23'), ['WS-CELL']);
  });
});

describe('evalCondition: what it rejects', () => {
  test('a name the resolver does not know is an error that names it', () => {
    assert.throws(() => holds('WS-MISSING = 1'), /WS-MISSING is not a field/);
  });

  test('an unknown name is an error even when the other side of an OR holds', () => {
    assert.throws(() => holds('WS-QTY = 9 OR WS-MISSING = 1'), /WS-MISSING/);
  });

  test('a condition that ends after the operator is incomplete', () => {
    assert.throws(() => holds('WS-QTY ='), /incomplete/);
    assert.throws(() => holds('WS-QTY = 9 AND'), /incomplete/);
  });

  test('a field alone is not a condition', () => {
    assert.throws(() => holds('WS-QTY'));
  });

  test('two operands without an operator are rejected', () => {
    assert.throws(() => holds('WS-QTY 9'), /expected an operator/);
  });

  test('what is left after a complete condition is rejected', () => {
    assert.throws(() => holds('WS-QTY = 9 WS-NET'), /unexpected trailing/);
    assert.throws(() => holds('(WS-QTY = 9))'), /unexpected trailing/);
  });

  test('a parenthesis that is never closed is rejected', () => {
    assert.throws(() => holds('(WS-QTY = 9'));
  });

  test('a literal that is never closed is rejected', () => {
    assert.throws(() => holds('WS-CATEGORY = "PREMIUM'), /unterminated/);
  });

  test('an empty condition is rejected', () => {
    assert.throws(() => holds(''));
  });
});

describe('conditionNames', () => {
  test('the fields of a condition are listed without keywords, literals or numbers', () => {
    assert.deepEqual(conditionNames('WS-NET > 1000 AND NOT WS-CATEGORY = "X" OR WS-QTY IS LESS THAN 5'), ['WS-NET', 'WS-CATEGORY', 'WS-QTY']);
  });

  test('the names are given in uppercase', () => {
    assert.deepEqual(conditionNames('ws-net > ws-qty'), ['WS-NET', 'WS-QTY']);
  });

  test('a field with subscripts is listed by its name', () => {
    assert.deepEqual(conditionNames('WS-ROW(2) = 20'), ['WS-ROW']);
  });

  test('words inside a literal are not fields', () => {
    assert.deepEqual(conditionNames("WS-MSG = 'WS-OTHER AND WS-MORE'"), ['WS-MSG']);
  });

  test('a name may start with a digit', () => {
    assert.deepEqual(conditionNames('1ST-AMOUNT > 0'), ['1ST-AMOUNT']);
  });

  test('a C expression has no COBOL names', () => {
    assert.deepEqual(conditionNames('b_32[0] == 1'), []);
    assert.deepEqual(conditionNames('count_1 > 3 && flag'), []);
  });

  test('a condition with a literal that is never closed has no names', () => {
    assert.deepEqual(conditionNames('WS-MSG = "open'), []);
  });

  test('a name that starts with two or more digits is read whole', () => {
    const five = (): Operand => ({ kind: 'number', value: { value: 5n, scale: 0 } });
    assert.deepEqual(conditionNames('100-TOTAL = 5'), ['100-TOTAL']);
    assert.equal(evalCondition('100-TOTAL = 5', five), true);
    assert.equal(evalCondition('100-TOTAL > 100', five), false);
  });
});

describe('operandOf', () => {
  test('a numeric DISPLAY field is a number with its sign and decimals', () => {
    assert.deepEqual(operandOf(ascii('001234u'), DISPLAY_S5V2), { kind: 'number', value: { value: -12345n, scale: 2 } });
  });

  test('packed and binary fields are numbers too', () => {
    assert.deepEqual(operandOf(hex('00 12 34 5d'), COMP3_S5V2), { kind: 'number', value: { value: -12345n, scale: 2 } });
    assert.deepEqual(operandOf(hex('04 d2'), COMP_4), { kind: 'number', value: { value: 1234n, scale: 0 } });
    assert.deepEqual(operandOf(hex('fe ff'), COMP5_S4), { kind: 'number', value: { value: -2n, scale: 0 } });
  });

  test('an alphanumeric field is its text, without quotes and with its spaces', () => {
    assert.deepEqual(operandOf(ascii('AB    '), ALNUM_6), { kind: 'text', value: 'AB    ' });
  });

  test('a group and an edited field are text', () => {
    assert.deepEqual(operandOf(ascii('AB12'), GROUP_4), { kind: 'text', value: 'AB12' });
    assert.deepEqual(operandOf(ascii('  3.50'), EDITED_6), { kind: 'text', value: '  3.50' });
  });

  test('the text of an alphanumeric field with a quote or a backslash is its bytes', () => {
    assert.deepEqual(operandOf(ascii('a"b\\c '), ALNUM_6), { kind: 'text', value: 'a"b\\c ' });
  });
});

describe('looksLikeC: a breakpoint condition left to the debugger', () => {
  test('a COBOL condition is not C, also with a decimal literal', () => {
    for (const c of ['WS-NET > 1600.50', 'WS-QTY = 9 AND WS-RATE < .5', 'WS-CELL(2, 3) NOT = 0', "WS-CATEGORY = 'PREMIUM'"]) {
      assert.equal(looksLikeC(c), false, c);
    }
  });

  test('member access, an index, C logical operators and generated names are C', () => {
    for (const c of ['p->size == 4', 'rec.count > 2', 'b_8[0] == 65', 'a == 1 && c == 2', 'a == 1 || c == 2', 'f_12.size > 0']) {
      assert.equal(looksLikeC(c), true, c);
    }
  });
});
