// Unit tests for src/dap/cobol-map.ts: the map between COBOL fields and the C
// statics of GnuCOBOL. The fixtures are short excerpts written by hand in the
// shape of what cobc generates (.c.l.h, .c and .i).

import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { after, before, describe, test } from 'node:test';
import { entryParameters, loadBuildMaps, ProgramMap, programFromFunction, usingParameters } from '../../dap/cobol-map';

/** Local storage of a program with a file, WORKING-STORAGE and no parameters. */
const INVOICE_H = [
  "/* Program local variables for 'INVOICE' */",
  '',
  '/* LINKAGE SECTION (Items not referenced by USING clause) */',
  'static unsigned char\t*b_14 = NULL;  /* XML-TEXT */',
  '',
  '/* Data storage */',
  'static int\tb_2;\t/* RETURN-CODE */',
  'static cob_u8_t\tb_21[23] __attribute__((aligned));\t/* CUST-FILE Record */',
  'static cob_u8_t\tb_26[1] __attribute__((aligned));\t/* WS-EOF */',
  'static cob_u8_t\tb_28[23] __attribute__((aligned));\t/* WS-CUST */',
  'static cob_u8_t\tb_40[8] __attribute__((aligned));\t/* WS-UNUSED */',
  '',
  '/* Fields (local) */',
  'static cob_field f_21\t= {23, b_21, &a_2};\t/* CUST-REC */',
  'static cob_field f_26\t= {1, b_26, &a_3};\t/* WS-EOF */',
  'static cob_field f_28\t= {23, b_28, &a_2};\t/* WS-CUST */',
  'static cob_field f_29\t= {5, b_28, &a_4};\t/* WS-CUST-ID */',
  'static cob_field f_30\t= {18, b_28 + 5, &a_5};\t/* WS-CUST-NAME */',
  '',
].join('\n');

/** Local storage of a subprogram with three parameters; the third has no descriptor. */
const DISCOUNT_H = [
  "/* Program local variables for 'DISCOUNT' */",
  '',
  '/* Data storage */',
  'static cob_u8_t\tb_17[3] __attribute__((aligned));\t/* WS-RATE */',
  '',
  '/* Fields (local) */',
  'static cob_field f_17\t= {3, b_17, &a_2};\t/* WS-RATE */',
  'static cob_field f_18\t= {9, NULL, &a_1};\t/* LN-AMOUNT */',
  'static cob_field f_19\t= {9, NULL, &a_1};\t/* LN-RESULT */',
  '',
].join('\n');

const DISCOUNT_ENTRY = ["/* ENTRY 'DISCOUNT' */", '', 'int', 'DISCOUNT (cob_u8_t *b_18, cob_u8_t *b_19, cob_u8_t *b_20)', '{'];

/** The .c as cobc 3.2 writes it: each parameter documented with its COBOL name. */
const DISCOUNT_C = [
  ...DISCOUNT_ENTRY,
  '  cob_u8_t *cob_parm_18 = NULL;\t/* linkage for LN-AMOUNT */',
  '  cob_u8_t *cob_parm_19 = NULL;\t/* linkage for LN-RESULT */',
  '  cob_u8_t *cob_parm_20 = NULL;\t/* linkage for LN-CATEGORY */',
  '  return DISCOUNT_ (0, cob_parm_18, cob_parm_19, cob_parm_20);',
  '}',
  '',
].join('\n');

/** The .c as cobc 3.1 writes it: no names for the parameters. */
const DISCOUNT_C_UNNAMED = [...DISCOUNT_ENTRY, '  return DISCOUNT_ (0, b_18, b_19, b_20);', '}', ''].join('\n');

const DISCOUNT_I = [
  '# 1 "src/DISCOUNT.cbl"',
  '       IDENTIFICATION DIVISION.',
  '       PROGRAM-ID. DISCOUNT.',
  '       DATA DIVISION.',
  '       LINKAGE SECTION.',
  '       01  LN-AMOUNT    PIC 9(7)V99.',
  '       01  LN-RESULT    PIC 9(7)V99.',
  '       01  LN-CATEGORY  PIC X(10).',
  '       PROCEDURE DIVISION USING LN-AMOUNT LN-RESULT LN-CATEGORY.',
  '           GOBACK.',
  '',
].join('\n');

describe('ProgramMap.parse: statics and fields', () => {
  test('a static with its own field has name, size and that field', () => {
    const st = ProgramMap.parse('INVOICE', INVOICE_H).statics.get('b_26');
    assert.ok(st);
    assert.deepEqual([st.id, st.name, st.size], ['b_26', 'WS-EOF', 1]);
    assert.deepEqual(st.field, { field: 'f_26', name: 'WS-EOF', size: 1, base: 'b_26', offset: 0 });
  });

  test('the field that covers a group is the field of the static', () => {
    const st = ProgramMap.parse('INVOICE', INVOICE_H).statics.get('b_28');
    assert.equal(st?.field?.field, 'f_28');
  });

  test('subordinate fields are children of their static, with their offsets', () => {
    const st = ProgramMap.parse('INVOICE', INVOICE_H).statics.get('b_28');
    assert.deepEqual(st?.children.map((c) => [c.name, c.field, c.offset, c.size]), [
      ['WS-CUST-ID', 'f_29', 0, 5],
      ['WS-CUST-NAME', 'f_30', 5, 18],
    ]);
  });

  test('a static never referenced as a field has no field and no children', () => {
    const st = ProgramMap.parse('INVOICE', INVOICE_H).statics.get('b_40');
    assert.ok(st);
    assert.equal(st.name, 'WS-UNUSED');
    assert.equal(st.field, undefined);
    assert.deepEqual(st.children, []);
  });

  test('the buffer of a file takes the name of its 01', () => {
    const st = ProgramMap.parse('INVOICE', INVOICE_H).statics.get('b_21');
    assert.equal(st?.name, 'CUST-REC');
    assert.equal(st?.field?.field, 'f_21');
  });

  test('an internal register of GnuCOBOL is marked as internal', () => {
    const st = ProgramMap.parse('INVOICE', INVOICE_H).statics.get('b_14');
    assert.equal(st?.name, 'XML-TEXT');
    assert.equal(st?.internal, true);
  });

  test('a storage that is not a COBOL record is not in the map', () => {
    assert.equal(ProgramMap.parse('INVOICE', INVOICE_H).statics.has('b_2'), false);
  });

  test('a field is found by name, whatever the case', () => {
    const map = ProgramMap.parse('INVOICE', INVOICE_H.replace('/* WS-CUST-NAME */', '/* Ws-Cust-Name */'));
    assert.equal(map.byName.get('WS-CUST-NAME')?.field, 'f_30');
  });

  test('of two fields with the same name the first declared is the one found by name', () => {
    const header = INVOICE_H + 'static cob_field f_31\t= {5, b_40, &a_4};\t/* WS-CUST-ID */\n';
    assert.equal(ProgramMap.parse('INVOICE', header).byName.get('WS-CUST-ID')?.field, 'f_29');
  });

  test('the map keeps the name of its program', () => {
    assert.equal(ProgramMap.parse('INVOICE', INVOICE_H).program, 'INVOICE');
  });
});

describe('ProgramMap.parse: LINKAGE parameters', () => {
  test('a parameter with a descriptor is a linkage static numbered like its field', () => {
    const st = ProgramMap.parse('DISCOUNT', DISCOUNT_H, DISCOUNT_C).statics.get('b_18');
    assert.ok(st);
    assert.deepEqual([st.name, st.size, st.linkage], ['LN-AMOUNT', 9, true]);
    assert.equal(st.field?.field, 'f_18');
    assert.equal(st.field?.base, undefined);
  });

  test('a parameter with a descriptor is known even without the .c', () => {
    const st = ProgramMap.parse('DISCOUNT', DISCOUNT_H).statics.get('b_19');
    assert.deepEqual([st?.name, st?.size, st?.linkage], ['LN-RESULT', 9, true]);
  });

  test('a parameter without a descriptor takes its name from the "linkage for" comment of the .c', () => {
    const st = ProgramMap.parse('DISCOUNT', DISCOUNT_H, DISCOUNT_C).statics.get('b_20');
    assert.ok(st);
    assert.deepEqual([st.name, st.linkage, st.field], ['LN-CATEGORY', true, undefined]);
  });

  test('without those comments the names come from the USING list by position', () => {
    const map = ProgramMap.parse('DISCOUNT', DISCOUNT_H, DISCOUNT_C_UNNAMED, DISCOUNT_I);
    assert.deepEqual(['b_18', 'b_19', 'b_20'].map((id) => map.statics.get(id)?.name), ['LN-AMOUNT', 'LN-RESULT', 'LN-CATEGORY']);
    assert.equal(map.statics.get('b_20')?.linkage, true);
  });

  test('when the USING list and the entry function disagree in number no name is guessed', () => {
    const shorter = DISCOUNT_I.replace('USING LN-AMOUNT LN-RESULT LN-CATEGORY.', 'USING LN-AMOUNT LN-RESULT.');
    const map = ProgramMap.parse('DISCOUNT', DISCOUNT_H, DISCOUNT_C_UNNAMED, shorter);
    assert.equal(map.statics.has('b_20'), false);
  });

  test('a local static is not a linkage parameter', () => {
    const st = ProgramMap.parse('DISCOUNT', DISCOUNT_H, DISCOUNT_C).statics.get('b_17');
    assert.ok(st);
    assert.ok(!st.linkage);
  });
});

describe('ProgramMap expressions', () => {
  const map = ProgramMap.parse('DISCOUNT', DISCOUNT_H, DISCOUNT_C);
  const local = map.byName.get('WS-RATE')!;
  const parameter = map.byName.get('LN-AMOUNT')!;

  test('the value of a local field is formatted from its descriptor', () => {
    const expression = ProgramMap.valueExpression(local);
    assert.ok(expression.includes('&f_17'));
    assert.ok(!expression.includes('.data ='));
  });

  test('the value of a parameter first points the descriptor at the pointer received', () => {
    const expression = ProgramMap.valueExpression(parameter);
    assert.ok(expression.includes('f_18.data = b_18'));
    assert.ok(expression.includes('&f_18'));
  });

  test('the raw bytes of a subordinate field are read at its offset in the static', () => {
    const name = ProgramMap.parse('INVOICE', INVOICE_H).byName.get('WS-CUST-NAME')!;
    assert.equal(ProgramMap.rawExpression(name).replace(/\s/g, ''), '(char*)(b_28+5)');
  });

  test('the raw bytes of a parameter are read from the pointer received', () => {
    assert.equal(ProgramMap.rawExpression(parameter).replace(/\s/g, ''), '(char*)b_18');
  });
});

describe('usingParameters', () => {
  test('the names of the USING list come in order', () => {
    assert.deepEqual(usingParameters('DISCOUNT', DISCOUNT_I), ['LN-AMOUNT', 'LN-RESULT', 'LN-CATEGORY']);
  });

  test('a USING list that continues on the following lines is read whole', () => {
    const source = DISCOUNT_I.replace('USING LN-AMOUNT LN-RESULT LN-CATEGORY.', 'USING LN-AMOUNT\n               LN-RESULT\n               LN-CATEGORY.');
    assert.deepEqual(usingParameters('DISCOUNT', source), ['LN-AMOUNT', 'LN-RESULT', 'LN-CATEGORY']);
  });

  test('BY REFERENCE, BY VALUE and OPTIONAL are not names', () => {
    const source = DISCOUNT_I.replace('USING LN-AMOUNT LN-RESULT LN-CATEGORY.', 'USING BY REFERENCE LN-AMOUNT, BY VALUE LN-RESULT\n               OPTIONAL LN-CATEGORY.');
    assert.deepEqual(usingParameters('DISCOUNT', source), ['LN-AMOUNT', 'LN-RESULT', 'LN-CATEGORY']);
  });

  test('the item after RETURNING is not a parameter', () => {
    const source = DISCOUNT_I.replace('USING LN-AMOUNT LN-RESULT LN-CATEGORY.', 'USING LN-AMOUNT LN-CATEGORY RETURNING LN-RESULT.');
    assert.deepEqual(usingParameters('DISCOUNT', source), ['LN-AMOUNT', 'LN-CATEGORY']);
  });

  test('a source in lowercase gives the names in uppercase', () => {
    assert.deepEqual(usingParameters('DISCOUNT', DISCOUNT_I.toLowerCase()), ['LN-AMOUNT', 'LN-RESULT', 'LN-CATEGORY']);
  });

  test('sequence numbers in columns 1 to 6 are not names', () => {
    const source = ['000100 IDENTIFICATION DIVISION.', '000200 PROGRAM-ID. DISCOUNT.', '000300 PROCEDURE DIVISION USING LN-AMOUNT', '000400     LN-RESULT.', '000500     GOBACK.', ''].join('\n');
    assert.deepEqual(usingParameters('DISCOUNT', source), ['LN-AMOUNT', 'LN-RESULT']);
  });

  test('in a source with several programs each one gets its own list', () => {
    const source = DISCOUNT_I + ['       IDENTIFICATION DIVISION.', '       PROGRAM-ID. PREMIUM.', '       PROCEDURE DIVISION USING LN-AGE LN-PREMIUM.', '           GOBACK.', ''].join('\n');
    assert.deepEqual(usingParameters('PREMIUM', source), ['LN-AGE', 'LN-PREMIUM']);
    assert.deepEqual(usingParameters('DISCOUNT', source), ['LN-AMOUNT', 'LN-RESULT', 'LN-CATEGORY']);
  });

  test('a program without USING has no parameters, even if a CALL below uses the word', () => {
    const source = ['       PROGRAM-ID. INVOICE.', '       PROCEDURE DIVISION.', '       0000-MAIN.', '           CALL "DISCOUNT" USING WS-AMOUNT WS-NET.', ''].join('\n');
    assert.deepEqual(usingParameters('INVOICE', source), []);
  });

  test('a program that is not in the source has no parameters', () => {
    assert.deepEqual(usingParameters('PREMIUM', DISCOUNT_I), []);
  });

  test('without the preprocessed source there are no parameters', () => {
    assert.deepEqual(usingParameters('DISCOUNT', ''), []);
  });

  test('a program whose name is the start of another (LOAN and LOAN-CALC) gets its own list', () => {
    const source = [
      '       PROGRAM-ID. LOAN-CALC.',
      '       PROCEDURE DIVISION USING LN-A LN-B.',
      '       END PROGRAM LOAN-CALC.',
      '       PROGRAM-ID. LOAN.',
      '       PROCEDURE DIVISION USING LN-X.',
    ].join('\n');
    assert.deepEqual(usingParameters('LOAN', source), ['LN-X']);
    assert.deepEqual(usingParameters('LOAN-CALC', source), ['LN-A', 'LN-B']);
  });
});

describe('entryParameters', () => {
  test('the parameters of the entry function come in order', () => {
    assert.deepEqual(entryParameters('DISCOUNT', DISCOUNT_C), ['b_18', 'b_19', 'b_20']);
  });

  test('the program is matched whatever the case', () => {
    assert.deepEqual(entryParameters('discount', DISCOUNT_C), ['b_18', 'b_19', 'b_20']);
  });

  test('in a .c with several entries each program gets its own', () => {
    const other = ["/* ENTRY 'PREMIUM' */", '', 'int', 'PREMIUM (cob_u8_t *b_31, cob_u8_t *b_32)', '{', '}', ''].join('\n');
    assert.deepEqual(entryParameters('PREMIUM', DISCOUNT_C + other), ['b_31', 'b_32']);
  });

  test('an entry function without parameters has none', () => {
    const main = ["/* ENTRY 'INVOICE' */", '', 'int', 'INVOICE ()', '{', '}', ''].join('\n');
    assert.deepEqual(entryParameters('INVOICE', main), []);
  });

  test('a program without an entry in the .c has none', () => {
    assert.deepEqual(entryParameters('PREMIUM', DISCOUNT_C), []);
    assert.deepEqual(entryParameters('DISCOUNT', ''), []);
  });
});

describe('programFromFunction', () => {
  test('the internal function of a program (NAME_) gives its PROGRAM-ID', () => {
    assert.equal(programFromFunction('TSTINV_'), 'TSTINV');
  });

  test('the entry function (NAME) gives its PROGRAM-ID', () => {
    assert.equal(programFromFunction('DISCOUNT'), 'DISCOUNT');
  });

  test('a frame name with its signature gives the PROGRAM-ID', () => {
    assert.equal(programFromFunction('DISCOUNT_ (int, unsigned char *, unsigned char *)'), 'DISCOUNT');
    assert.equal(programFromFunction('DISCOUNT_(int)'), 'DISCOUNT');
  });

  test('the double underscore cobc writes for a hyphen becomes a hyphen again', () => {
    assert.equal(programFromFunction('LOAN__CALC_'), 'LOAN-CALC');
  });

  test('the PROGRAM-ID is given in uppercase', () => {
    assert.equal(programFromFunction('tstinv_'), 'TSTINV');
  });

  test('a frame without a function name gives no program', () => {
    assert.equal(programFromFunction(undefined), undefined);
    assert.equal(programFromFunction(''), undefined);
  });
});

describe('loadBuildMaps', () => {
  let tmp = '';
  let count = 0;

  before(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cobalto-cobol-map-'));
  });

  after(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  function buildDir(files: Record<string, string>): string {
    const dir = path.join(tmp, `build-${++count}`);
    fs.mkdirSync(dir);
    for (const [name, content] of Object.entries(files)) {
      fs.writeFileSync(path.join(dir, name), content);
    }
    return dir;
  }

  test('each .c.l.h of the folder becomes the map of its program', () => {
    const maps = loadBuildMaps(buildDir({ 'INVOICE.c.l.h': INVOICE_H, 'DISCOUNT.c.l.h': DISCOUNT_H, 'INVOICE.c': '', 'INVOICE.lst': 'not a map' }));
    assert.deepEqual([...maps.keys()].sort(), ['DISCOUNT', 'INVOICE']);
    assert.equal(maps.get('INVOICE')?.byName.get('WS-EOF')?.field, 'f_26');
  });

  test('the program is the one the header names, not the file', () => {
    const maps = loadBuildMaps(buildDir({ 'CBLTLIB.c.l3.h': DISCOUNT_H }));
    assert.deepEqual([...maps.keys()], ['DISCOUNT']);
  });

  test('a header that names no program is indexed by its file name', () => {
    const anonymous = DISCOUNT_H.split('\n').slice(1).join('\n');
    const maps = loadBuildMaps(buildDir({ 'discount.c.l.h': anonymous }));
    assert.deepEqual([...maps.keys()], ['DISCOUNT']);
  });

  test('the .c next to the header names the parameters without a descriptor', () => {
    const maps = loadBuildMaps(buildDir({ 'DISCOUNT.c.l.h': DISCOUNT_H, 'DISCOUNT.c': DISCOUNT_C }));
    assert.equal(maps.get('DISCOUNT')?.statics.get('b_20')?.name, 'LN-CATEGORY');
  });

  test('the .i next to the header names them when the .c does not', () => {
    const maps = loadBuildMaps(buildDir({ 'DISCOUNT.c.l.h': DISCOUNT_H, 'DISCOUNT.c': DISCOUNT_C_UNNAMED, 'DISCOUNT.i': DISCOUNT_I }));
    assert.equal(maps.get('DISCOUNT')?.statics.get('b_20')?.name, 'LN-CATEGORY');
  });

  test('a folder that does not exist gives no maps', () => {
    assert.equal(loadBuildMaps(path.join(tmp, 'does-not-exist')).size, 0);
  });
});
