// Map between COBOL fields and GnuCOBOL's C statics, read from the
// build/<prog>.c.l.h files that cobc generates. Each item with its own storage is a
// "static cob_u8_t b_NNN[len]; /* NAME */" and each field (including the
// subordinate ones) a "static cob_field f_NN = {size, b_NNN + off, &a_K}; /* NAME */".
// LINKAGE parameters have a NULL base and reach the C function as
// "cob_u8_t *b_NN", with the same number as their f_NN. A parameter without a
// descriptor (not referenced as a field) only has a name in the "linkage for"
// comment of the .c (cobc 3.2) or, if the compiler does not write it (cobc
// 3.1), by position: the USING list of the preprocessed build/<prog>.i against
// the parameters of the entry function in the .c.

import * as fs from 'fs';
import * as path from 'path';

export interface CobolField {
  /** cob_field descriptor, for example f_32 */
  field: string;
  /** COBOL name, for example WS-AMOUNT */
  name: string;
  size: number;
  /** static base (b_NNN) or undefined for LINKAGE */
  base?: string;
  offset: number;
}

export interface CobolStatic {
  /** b_NNN */
  id: string;
  name: string;
  size: number;
  /** GnuCOBOL internal record (XML-*, JSON-*), without a useful descriptor */
  internal?: boolean;
  /** field that covers the static exactly, if there is one */
  field?: CobolField;
  /** LINKAGE parameter (pointer received by the C function) */
  linkage?: boolean;
  /** subordinate fields (other f_NN on the same base) */
  children: CobolField[];
}

const STATIC_RE = /static\s+cob_u8_t\s+(b_\d+)\[(\d+)\][^;]*;\s*\/\*\s*(.+?)\s*\*\//g;
const FIELD_RE = /static\s+cob_field\s+(f_\d+)\s*=\s*\{(\d+),\s*(b_\d+|NULL)(?:\s*\+\s*(\d+))?,\s*&a_\d+\};\s*\/\*\s*(.+?)\s*\*\//g;
const POINTER_RE = /static\s+unsigned\s+char\s*\*\s*(b_\d+)\s*=\s*NULL;\s*\/\*\s*(.+?)\s*\*\//g;
const PARM_RE = /cob_parm_(\d+)\s*=\s*NULL;\s*\/\*\s*linkage for\s+(.+?)\s*\*\//g;
const PROGRAM_RE = /\/\*\s*Program local variables for '([^']+)'\s*\*\//;
// entry function in the .c: /* ENTRY 'NAME' */ int C_NAME (cob_u8_t *b_9, ...)
const ENTRY_RE = /\/\*\s*ENTRY\s+'([^']+)'\s*\*\/\s*(?:static\s+)?int\s+[A-Za-z0-9_]+\s*\(([^)]*)\)/g;

export class ProgramMap {
  readonly statics = new Map<string, CobolStatic>();
  readonly byName = new Map<string, CobolField>();

  constructor(readonly program: string) {}

  static parse(program: string, text: string, cText = '', iText = ''): ProgramMap {
    const map = new ProgramMap(program);
    for (const m of text.matchAll(STATIC_RE)) {
      map.statics.set(m[1], { id: m[1], name: m[3], size: parseInt(m[2], 10), children: [] });
    }
    for (const m of text.matchAll(POINTER_RE)) {
      map.statics.set(m[1], { id: m[1], name: m[2], size: 0, internal: true, children: [] });
    }
    // LINKAGE parameters: the .c documents them even without a descriptor
    for (const m of cText.matchAll(PARM_RE)) {
      const id = 'b_' + m[1];
      if (!map.statics.has(id)) {
        map.statics.set(id, { id, name: m[2], size: 0, linkage: true, children: [] });
      }
    }
    // without "linkage for" comments (cobc 3.1): names by position in USING
    const usingNames = usingParameters(program, iText);
    const entryIds = entryParameters(program, cText);
    if (usingNames.length && usingNames.length === entryIds.length) {
      entryIds.forEach((id, i) => {
        if (!map.statics.has(id)) {
          map.statics.set(id, { id, name: usingNames[i], size: 0, linkage: true, children: [] });
        }
      });
    }
    for (const m of text.matchAll(FIELD_RE)) {
      const f: CobolField = {
        field: m[1],
        size: parseInt(m[2], 10),
        base: m[3] === 'NULL' ? undefined : m[3],
        offset: m[4] ? parseInt(m[4], 10) : 0,
        name: m[5],
      };
      if (!map.byName.has(f.name.toUpperCase())) {
        map.byName.set(f.name.toUpperCase(), f);
      }
      if (f.base) {
        const st = map.statics.get(f.base);
        if (!st) {
          continue;
        }
        if (f.offset === 0 && f.size === st.size && !st.field) {
          st.field = f;
          // cobc registers "CUST-FILE Record" for the FD buffer and then the
          // 01 with its real name: we prefer the name of the 01
          if (/ Record$/.test(st.name) && !/ Record$/.test(f.name)) {
            st.name = f.name;
          }
        } else {
          st.children.push(f);
        }
      } else {
        // LINKAGE: the C function receives the pointer as b_NN with the field's number
        const id = 'b_' + f.field.slice(2);
        const existing = map.statics.get(id);
        if (!existing) {
          map.statics.set(id, { id, name: f.name, size: f.size, field: f, linkage: true, children: [] });
        } else if (!existing.field) {
          existing.field = f;
          existing.size = f.size;
          existing.linkage = true;
        }
      }
    }
    return map;
  }

  /** Expression that libcob evaluates to the formatted value of the field. For a
   *  LINKAGE parameter the descriptor receives the parameter's pointer, as
   *  the generated code itself does before each use. */
  static valueExpression(field: CobolField): string {
    if (!field.base) {
      return `(${field.field}.data = b_${field.field.slice(2)}, (char*)cob_get_field_str_buffered(&${field.field}))`;
    }
    return `(char*)cob_get_field_str_buffered(&${field.field})`;
  }

  /** Fallback expression: the bytes of the field as a C string. */
  static rawExpression(field: CobolField): string {
    return field.base ? `(char*)(${field.base} + ${field.offset})` : `(char*)b_${field.field.slice(2)}`;
  }
}

/** Reads every build/*.c.l*.h and indexes them by PROGRAM-ID. */
export function loadBuildMaps(buildDir: string, log?: (s: string) => void): Map<string, ProgramMap> {
  const result = new Map<string, ProgramMap>();
  let names: string[];
  try {
    names = fs.readdirSync(buildDir).filter((n) => /\.c\.l\d*\.h$/.test(n));
  } catch {
    return result;
  }
  for (const n of names) {
    try {
      const text = fs.readFileSync(path.join(buildDir, n), 'utf8');
      const pm = PROGRAM_RE.exec(text);
      const program = pm ? pm[1].toUpperCase() : n.replace(/\.c\.l\d*\.h$/, '').toUpperCase();
      let cText = '';
      try {
        cText = fs.readFileSync(path.join(buildDir, n.replace(/\.c\.l\d*\.h$/, '.c')), 'utf8');
      } catch {
        cText = '';
      }
      let iText = '';
      try {
        iText = fs.readFileSync(path.join(buildDir, n.replace(/\.c\.l\d*\.h$/, '.i')), 'utf8');
      } catch {
        iText = '';
      }
      const map = ProgramMap.parse(program, text, cText, iText);
      result.set(program, map);
      log?.(`map of ${program}: ${map.statics.size} statics, ${map.byName.size} fields (${n})`);
    } catch (e) {
      log?.(`could not read ${n}: ${String(e)}`);
    }
  }
  return result;
}

/** Names in the USING clause of the program's PROCEDURE DIVISION, in order,
 *  read from the preprocessed source (.i, which may hold several programs). */
export function usingParameters(program: string, iText: string): string[] {
  if (!iText) {
    return [];
  }
  const lines = iText.split(/\r?\n/).filter((l) => !/^#/.test(l));
  const upper = lines.map((l) => l.toUpperCase());
  // the name whole: LOAN is not the start of LOAN-CALC
  const progRe = new RegExp(`\\bPROGRAM-ID\\.?\\s+"?${program.replace(/[-]/g, '\\-')}(?![A-Za-z0-9-])`, 'i');
  const start = upper.findIndex((l) => progRe.test(l));
  if (start < 0) {
    return [];
  }
  const from = upper.findIndex((l, i) => i > start && /\bPROCEDURE\s+DIVISION\b/.test(l));
  if (from < 0) {
    return [];
  }
  let stmt = '';
  for (let i = from; i < upper.length && i < from + 50; i++) {
    stmt += ' ' + upper[i].replace(/^\s{0,6}[0-9 ]{0,6}/, '');
    if (/\.\s*$/.test(upper[i])) {
      break;
    }
  }
  const m = /\bUSING\b([\s\S]*?)(?:\bRETURNING\b|\.\s*$)/.exec(stmt);
  if (!m) {
    return [];
  }
  return m[1]
    .split(/[\s,]+/)
    .filter((t) => t && !/^(BY|REFERENCE|VALUE|CONTENT|OPTIONAL|SIZE|IS|AUTO|DEFAULT|UNSIGNED|DELIMITED)$/.test(t));
}

/** Parameters (b_NN) of the program's entry function in the .c, in order. */
export function entryParameters(program: string, cText: string): string[] {
  if (!cText) {
    return [];
  }
  for (const m of cText.matchAll(ENTRY_RE)) {
    if (m[1].toUpperCase() !== program.toUpperCase()) {
      continue;
    }
    return Array.from(m[2].matchAll(/\bb_(\d+)\b/g)).map((p) => 'b_' + p[1]);
  }
  return [];
}

/** PROGRAM-ID from the name of the generated C function (TSTINV_ -> TSTINV). */
export function programFromFunction(fn: string | undefined): string | undefined {
  if (!fn) {
    return undefined;
  }
  const m = /^([A-Za-z0-9_]+?)_?(?:\s*\(.*)?$/.exec(fn.trim());
  if (!m) {
    return undefined;
  }
  return m[1].replace(/__/g, '-').toUpperCase();
}
