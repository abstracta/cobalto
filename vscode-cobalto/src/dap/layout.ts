// Data layout of each program (build/<suite>.layout.json, written by
// "cobalto debug" from cobc's symbol listing): every item with its level,
// size, PIC, usage, OCCURS and offset within its 01. With the contents
// of the record read from the process memory, this module formats any
// field (including those cobc does not reference and the occurrences of an
// OCCURS), encodes a new value and evaluates COBOL conditions.

import * as fs from 'fs';
import { schemaProblem } from './schema';

export type ItemKind = 'group' | 'alnum' | 'display' | 'comp3' | 'binary' | 'comp5' | 'numedit' | 'index' | 'pointer' | 'float' | 'double';

export interface LayoutItem {
  name: string;
  level: number;
  section: string;
  kind: ItemKind;
  pic: string;
  usage: string;
  /** size of one occurrence */
  size: number;
  occurs: number;
  redefines: string | null;
  digits: number;
  scale: number;
  signed: boolean;
  sign_separate?: boolean;
  /** offset within the 01 (first occurrence of each OCCURS) */
  offset: number;
  children: LayoutItem[];
  unreliable?: boolean;
}

export interface ProgramLayout {
  source: string;
  items: LayoutItem[];
  warnings: string[];
}

/** A located item: its 01, the chain of OCCURS that contains it (from the
 *  outside in, itself included) and the 01 it belongs to. */
export interface Located {
  root: LayoutItem;
  item: LayoutItem;
  /** ancestors with OCCURS (the item included), from the outside in */
  dims: LayoutItem[];
}

export class Layout {
  readonly programs = new Map<string, ProgramLayout>();
  private readonly index = new Map<string, Map<string, Located[]>>();

  static load(jsonPath: string, log?: (s: string) => void): Layout | undefined {
    try {
      const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8')) as {
        schema?: number;
        cobalto?: string;
        programs: Record<string, ProgramLayout>;
      };
      const problem = schemaProblem(data, jsonPath);
      if (problem) {
        log?.(problem);
        return undefined;
      }
      const lay = new Layout();
      for (const [prog, pl] of Object.entries(data.programs ?? {})) {
        lay.programs.set(prog.toUpperCase(), pl);
        const byName = new Map<string, Located[]>();
        for (const root of pl.items) {
          const walk = (item: LayoutItem, dims: LayoutItem[]): void => {
            const d = item.occurs ? [...dims, item] : dims;
            const key = item.name.toUpperCase();
            const list = byName.get(key) ?? [];
            list.push({ root, item, dims: d });
            byName.set(key, list);
            for (const c of item.children) {
              walk(c, d);
            }
          };
          walk(root, []);
        }
        lay.index.set(prog.toUpperCase(), byName);
      }
      log?.(`data layout: ${lay.programs.size} programs (${jsonPath})`);
      return lay;
    } catch (e) {
      log?.(`no data layout (${jsonPath}): ${String(e)}`);
      return undefined;
    }
  }

  program(name: string | undefined): ProgramLayout | undefined {
    return name ? this.programs.get(name.toUpperCase()) : undefined;
  }

  /** 01 or 77 of a program by name and section. */
  root(program: string, name: string, sections?: string[]): LayoutItem | undefined {
    const pl = this.program(program);
    if (!pl) {
      return undefined;
    }
    const up = name.toUpperCase();
    return pl.items.find((r) => r.name === up && (!sections || sections.includes(r.section ?? 'FILE')) && !r.unreliable);
  }

  /** First item with that name in the program (declaration order). */
  find(program: string, name: string): Located | undefined {
    const list = this.index.get(program.toUpperCase())?.get(name.toUpperCase());
    return list?.find((l) => !l.root.unreliable);
  }
}

// ----------------------------------------------------------- references

/** COBOL name with optional subscripts: WS-T-QTY(2) or WS-N-VAL (1, 2). */
export interface Reference {
  name: string;
  subscripts: number[];
}

const REF_RE = /^([A-Za-z0-9][A-Za-z0-9-]*)\s*(?:\(\s*([0-9]+(?:\s*[, ]\s*[0-9]+)*)\s*\))?$/;

export function parseReference(text: string): Reference | undefined {
  const m = REF_RE.exec(text.trim());
  if (!m || !/[A-Za-z]/.test(m[1])) {
    return undefined;
  }
  const subs = m[2] ? m[2].split(/[\s,]+/).filter((s) => s).map((s) => parseInt(s, 10)) : [];
  return { name: m[1].toUpperCase(), subscripts: subs };
}

/** Absolute offset within the 01 of a reference with subscripts
 *  (each ancestor with OCCURS consumes one subscript; missing ones are 1). */
export function offsetOf(loc: Located, subscripts: number[]): { offset: number; error?: string } {
  if (subscripts.length > loc.dims.length) {
    return { offset: 0, error: `${loc.item.name} takes ${loc.dims.length} subscript(s)` };
  }
  let offset = loc.item.offset;
  loc.dims.forEach((d, i) => {
    const k = subscripts[i] ?? 1;
    if (k < 1 || k > d.occurs) {
      throw new Error(`subscript ${k} out of range 1..${d.occurs} in ${d.name}`);
    }
    offset += (k - 1) * d.size;
  });
  return { offset };
}

// ------------------------------------------------------------- formatting

function latin1(buf: Buffer): string {
  return buf.toString('latin1');
}

function quote(s: string): string {
  // control characters are what this replaces
  // eslint-disable-next-line no-control-regex
  return '"' + s.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/[\x00-\x1f\x7f]/g, '.') + '"';
}

/** The text inside the double quotes quote() adds, with its escapes undone. */
function unquote(s: string): string {
  return s.slice(1, -1).replace(/\\(["\\])/g, '$1');
}

/** Digits (unsigned) and sign of a numeric DISPLAY field according to
 *  GnuCOBOL's encoding (ASCII or EBCDIC overpunch, or separate sign). */
function decodeDisplay(buf: Buffer, item: LayoutItem): { digits: string; negative: boolean } {
  let s = latin1(buf);
  let negative = false;
  if (item.sign_separate) {
    if (s.startsWith('+') || s.startsWith('-')) {
      negative = s[0] === '-';
      s = s.slice(1);
    } else if (s.endsWith('+') || s.endsWith('-')) {
      negative = s[s.length - 1] === '-';
      s = s.slice(0, -1);
    }
  } else if (item.signed && s.length) {
    const c = s[s.length - 1];
    const code = c.charCodeAt(0);
    let digit: string | undefined;
    if (code >= 0x70 && code <= 0x79) {
      digit = String(code - 0x70);
      negative = true;
    } else if (c >= 'J' && c <= 'R') {
      digit = String(code - 'J'.charCodeAt(0) + 1);
      negative = true;
    } else if (c === '}') {
      digit = '0';
      negative = true;
    } else if (c >= 'A' && c <= 'I') {
      digit = String(code - 'A'.charCodeAt(0) + 1);
    } else if (c === '{') {
      digit = '0';
    }
    if (digit !== undefined) {
      s = s.slice(0, -1) + digit;
    }
  }
  return { digits: s, negative };
}

function withScale(digits: string, scale: number, negative: boolean): string {
  let d = digits.replace(/[^0-9]/g, '?');
  if (scale > 0) {
    d = d.padStart(scale + 1, '0');
    d = d.slice(0, d.length - scale) + '.' + d.slice(d.length - scale);
  }
  return (negative ? '-' : '') + d;
}

function bigToDigits(v: bigint, digits: number): { digits: string; negative: boolean } {
  const negative = v < 0n;
  const abs = negative ? -v : v;
  return { digits: abs.toString().padStart(digits, '0'), negative };
}

export function readInt(buf: Buffer, signed: boolean, littleEndian: boolean): bigint {
  let v = 0n;
  const bytes = littleEndian ? [...buf].reverse() : [...buf];
  for (const b of bytes) {
    v = (v << 8n) | BigInt(b);
  }
  if (signed && buf.length && (bytes[0] & 0x80)) {
    v -= 1n << BigInt(8 * buf.length);
  }
  return v;
}

/** The native endianness of the machine where the debugged program runs:
 *  COMP-5, INDEX and POINTER use it. GnuCOBOL stores COMP big-endian. */
const NATIVE_LE = true;

/** Formatted value of an item from its bytes (one occurrence). */
export function formatValue(buf: Buffer, item: LayoutItem): string {
  if (buf.length < item.size) {
    return `(${buf.length} of ${item.size} bytes readable)`;
  }
  const b = buf.subarray(0, item.size);
  switch (item.kind) {
    case 'display': {
      const { digits, negative } = decodeDisplay(b, item);
      return withScale(digits, item.scale, negative);
    }
    case 'comp3': {
      let digits = '';
      for (let i = 0; i < b.length; i++) {
        digits += (b[i] >> 4).toString(16) + (b[i] & 0x0f).toString(16);
      }
      const signNibble = b[b.length - 1] & 0x0f;
      digits = digits.slice(0, -1);
      const negative = signNibble === 0x0d || signNibble === 0x0b;
      const trimmed = item.digits ? digits.slice(digits.length - item.digits) : digits;
      return withScale(trimmed.replace(/[a-f]/g, '?'), item.scale, negative);
    }
    case 'binary':
    case 'comp5': {
      const v = readInt(b, item.signed, item.kind === 'comp5' && NATIVE_LE);
      const { digits, negative } = bigToDigits(v, item.digits);
      return withScale(digits, item.scale, negative);
    }
    case 'index':
      return readInt(b, true, NATIVE_LE).toString();
    case 'pointer':
      return '0x' + readInt(b, false, NATIVE_LE).toString(16).padStart(b.length * 2, '0');
    case 'float':
      return String(NATIVE_LE ? b.readFloatLE(0) : b.readFloatBE(0));
    case 'double':
      return String(NATIVE_LE ? b.readDoubleLE(0) : b.readDoubleBE(0));
    default:
      return quote(latin1(b));
  }
}

// ----------------------------------------------------------- writing

export interface Decimal {
  /** scaled integer value */
  value: bigint;
  scale: number;
}

const NUMBER_RE = /^([+-])?\s*(\d*)(?:\.(\d*))?$/;

export function parseDecimal(text: string): Decimal | undefined {
  const m = NUMBER_RE.exec(text.trim());
  if (!m || (!m[2] && !m[3])) {
    return undefined;
  }
  const int = m[2] || '0';
  const frac = m[3] || '';
  const value = BigInt(int + frac) * (m[1] === '-' ? -1n : 1n);
  return { value, scale: frac.length };
}

export function rescale(d: Decimal, scale: number): bigint {
  if (scale >= d.scale) {
    return d.value * 10n ** BigInt(scale - d.scale);
  }
  return d.value / 10n ** BigInt(d.scale - scale); // truncates, like a MOVE
}

/** Bytes of a new value for the item, honoring its encoding. `current`
 *  holds the current bytes (to keep the position of the separate sign). */
export function encodeValue(text: string, item: LayoutItem, current?: Buffer): Buffer {
  const isText = item.kind === 'alnum' || item.kind === 'group' || item.kind === 'numedit';
  if (isText) {
    let s = text;
    if (/^"[\s\S]*"$/.test(s.trim())) {
      // the form formatValue shows: what is displayed encodes back to the same bytes
      s = unquote(s.trim());
    } else if (/^'[\s\S]*'$/.test(s.trim())) {
      s = s.trim().slice(1, -1);
    }
    const out = Buffer.alloc(item.size, 0x20);
    out.write(s, 0, item.size, 'latin1');
    return out;
  }
  if (item.kind === 'pointer') {
    const v = BigInt(text.trim());
    const out = Buffer.alloc(item.size);
    for (let i = 0; i < item.size; i++) {
      out[NATIVE_LE ? i : item.size - 1 - i] = Number((v >> BigInt(8 * i)) & 0xffn);
    }
    return out;
  }
  if (item.kind === 'float' || item.kind === 'double') {
    const n = Number(text.trim());
    if (Number.isNaN(n)) {
      throw new Error(`"${text}" is not a number`);
    }
    const out = Buffer.alloc(item.size);
    if (item.kind === 'float' && NATIVE_LE) {
      out.writeFloatLE(n, 0);
    } else if (item.kind === 'float') {
      out.writeFloatBE(n, 0);
    } else if (NATIVE_LE) {
      out.writeDoubleLE(n, 0);
    } else {
      out.writeDoubleBE(n, 0);
    }
    return out;
  }
  const dec = parseDecimal(text);
  if (!dec) {
    throw new Error(`"${text}" is not a number`);
  }
  const v = rescale(dec, item.scale);
  const negative = v < 0n;
  if (negative && !item.signed && item.kind !== 'index') {
    throw new Error(`${item.name} is unsigned`);
  }
  const abs = negative ? -v : v;
  if (item.kind === 'index') {
    const out = Buffer.alloc(item.size);
    const u = v < 0n ? v + (1n << BigInt(8 * item.size)) : v;
    for (let i = 0; i < item.size; i++) {
      out[NATIVE_LE ? i : item.size - 1 - i] = Number((u >> BigInt(8 * i)) & 0xffn);
    }
    return out;
  }
  if (item.digits && abs.toString().length > item.digits) {
    throw new Error(`${text} does not fit in ${item.digits} digits (PIC ${item.pic})`);
  }
  if (item.kind === 'display') {
    let digits = abs.toString().padStart(item.digits, '0');
    if (item.sign_separate) {
      const sign = negative ? '-' : '+';
      const cur = current ? latin1(current) : '';
      const leading = cur.startsWith('+') || cur.startsWith('-') || !(cur.endsWith('+') || cur.endsWith('-'));
      return Buffer.from(leading ? sign + digits : digits + sign, 'latin1');
    }
    if (item.signed && negative) {
      const last = digits.charCodeAt(digits.length - 1) - 0x30;
      digits = digits.slice(0, -1) + String.fromCharCode(0x70 + last);
    }
    return Buffer.from(digits, 'latin1');
  }
  if (item.kind === 'comp3') {
    const nibbles = abs.toString().padStart(item.size * 2 - 1, '0') + (negative ? 'd' : item.signed ? 'c' : 'f');
    return Buffer.from(nibbles, 'hex');
  }
  // binary / comp5
  const out = Buffer.alloc(item.size);
  const u = v < 0n ? v + (1n << BigInt(8 * item.size)) : v;
  const le = item.kind === 'comp5' && NATIVE_LE;
  for (let i = 0; i < item.size; i++) {
    out[le ? i : item.size - 1 - i] = Number((u >> BigInt(8 * i)) & 0xffn);
  }
  return out;
}

// ---------------------------------------------------------- conditions

/** Value of an operand in a condition: decimal number or text. */
export type Operand = { kind: 'number'; value: Decimal } | { kind: 'text'; value: string };

export type Resolver = (ref: Reference) => Operand | undefined;

type Token = { t: 'name'; v: string } | { t: 'num'; v: string } | { t: 'str'; v: string } | { t: 'op'; v: string } | { t: 'kw'; v: string } | { t: '('; v: string } | { t: ')'; v: string };

const KEYWORDS = new Set(['AND', 'OR', 'NOT', 'EQUAL', 'EQUALS', 'GREATER', 'LESS', 'THAN', 'TO', 'OR', 'IS']);

function tokenize(text: string): Token[] {
  const out: Token[] = [];
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (/[\s,;]/.test(c)) {
      // in COBOL a comma or a semicolon is a separator, like a space
      i++;
      continue;
    }
    if (c === '(' || c === ')') {
      out.push({ t: c, v: c });
      i++;
      continue;
    }
    if (c === '"' || c === "'") {
      const j = text.indexOf(c, i + 1);
      if (j < 0) {
        throw new Error('unterminated literal');
      }
      out.push({ t: 'str', v: text.slice(i + 1, j) });
      i = j + 1;
      continue;
    }
    const op = /^(>=|<=|<>|!=|==|=|>|<)/.exec(text.slice(i));
    if (op) {
      out.push({ t: 'op', v: op[1] === '!=' ? '<>' : op[1] === '==' ? '=' : op[1] });
      i += op[1].length;
      continue;
    }
    const num = /^[+-]?(\d+\.?\d*|\.\d+)(?![A-Za-z0-9-])/.exec(text.slice(i));
    if (num) {
      out.push({ t: 'num', v: num[0] });
      i += num[0].length;
      continue;
    }
    const name = /^[A-Za-z0-9][A-Za-z0-9-]*/.exec(text.slice(i));
    if (name) {
      const up = name[0].toUpperCase();
      out.push(KEYWORDS.has(up) ? { t: 'kw', v: up } : { t: 'name', v: up });
      i += name[0].length;
      continue;
    }
    throw new Error(`unexpected character "${c}"`);
  }
  return out;
}

function cmpOperands(a: Operand, b: Operand, op: string): boolean {
  let c: number;
  if (a.kind === 'number' && b.kind === 'number') {
    const scale = Math.max(a.value.scale, b.value.scale);
    const x = rescale(a.value, scale);
    const y = rescale(b.value, scale);
    c = x < y ? -1 : x > y ? 1 : 0;
  } else {
    const x = a.kind === 'text' ? a.value : decimalToString(a.value);
    const y = b.kind === 'text' ? b.value : decimalToString(b.value);
    const n = Math.max(x.length, y.length);
    const xs = x.padEnd(n, ' ');
    const ys = y.padEnd(n, ' ');
    c = xs < ys ? -1 : xs > ys ? 1 : 0;
  }
  switch (op) {
    case '=':
      return c === 0;
    case '<>':
      return c !== 0;
    case '>':
      return c > 0;
    case '<':
      return c < 0;
    case '>=':
      return c >= 0;
    default:
      return c <= 0;
  }
}

export function decimalToString(d: Decimal): string {
  const { digits, negative } = bigToDigits(d.value, d.scale + 1);
  return withScale(digits, d.scale, negative);
}

/** Whether a breakpoint condition is a C expression for the debugger and not
 *  COBOL: it reaches into a structure or an array, uses C's logical
 *  operators or names a generated variable. A decimal point is not a sign
 *  of C: WS-NET > 1600.50 is COBOL. */
export function looksLikeC(text: string): boolean {
  return /->|\[|&&|\|\||\bb_\d+|\bf_\d+|[A-Za-z_)\]]\.[A-Za-z_]/.test(text);
}

/** COBOL names used by a condition (empty if it does not parse as a COBOL condition). */
export function conditionNames(text: string): string[] {
  try {
    return tokenize(text).filter((t) => t.t === 'name').map((t) => t.v);
  } catch {
    return [];
  }
}

/** Evaluates a simple COBOL condition: comparisons (=, <>, >, <, >=, <=,
 *  also EQUAL/GREATER THAN/LESS THAN), AND, OR, NOT and parentheses. */
export function evalCondition(text: string, resolve: Resolver): boolean {
  const toks = tokenize(text);
  let pos = 0;
  const peek = (): Token | undefined => toks[pos];
  const next = (): Token => {
    const t = toks[pos++];
    if (!t) {
      throw new Error('incomplete condition');
    }
    return t;
  };
  const operand = (): Operand => {
    const t = next();
    if (t.t === 'num') {
      const d = parseDecimal(t.v);
      if (!d) {
        throw new Error(`invalid number ${t.v}`);
      }
      return { kind: 'number', value: d };
    }
    if (t.t === 'str') {
      return { kind: 'text', value: t.v };
    }
    if (t.t === 'name') {
      const subs: number[] = [];
      if (peek()?.t === '(') {
        next();
        while (peek() && peek()!.t !== ')') {
          const s = next();
          if (s.t === 'num') {
            subs.push(parseInt(s.v, 10));
          }
        }
        next();
      }
      const v = resolve({ name: t.v, subscripts: subs });
      if (!v) {
        throw new Error(`${t.v} is not a field of the stopped program`);
      }
      return v;
    }
    throw new Error(`expected a field or literal but got "${t.v}"`);
  };
  const operator = (): string => {
    let t = next();
    let neg = false;
    if (t.t === 'kw' && t.v === 'IS') {
      t = next();
    }
    if (t.t === 'kw' && t.v === 'NOT') {
      neg = true;
      t = next();
    }
    if (t.t === 'op' || t.t === 'kw') {
      const kw = t.v;
      let op: string;
      if (t.t === 'op') {
        op = kw;
      } else if (kw === 'EQUAL' || kw === 'EQUALS') {
        if (peek()?.t === 'kw' && peek()!.v === 'TO') {
          next();
        }
        op = '=';
      } else if (kw === 'GREATER' || kw === 'LESS') {
        if (peek()?.t === 'kw' && peek()!.v === 'THAN') {
          next();
        }
        op = kw === 'GREATER' ? '>' : '<';
        if (peek()?.t === 'kw' && peek()!.v === 'OR') {
          next();
          const e = next();
          if (e.v === 'EQUAL' || e.v === 'EQUALS') {
            if (peek()?.t === 'kw' && peek()!.v === 'TO') {
              next();
            }
            op += '=';
          }
        }
      } else {
        throw new Error(`unknown operator ${kw}`);
      }
      if (neg) {
        op = { '=': '<>', '<>': '=', '>': '<=', '<': '>=', '>=': '<', '<=': '>' }[op] ?? op;
      }
      return op;
    }
    throw new Error(`expected an operator but got "${t.v}"`);
  };
  const factor = (): boolean => {
    const t = peek();
    if (t?.t === 'kw' && t.v === 'NOT') {
      next();
      return !factor();
    }
    if (t?.t === '(') {
      next();
      const v = expr();
      if (next().t !== ')') {
        throw new Error('missing )');
      }
      return v;
    }
    const a = operand();
    const op = operator();
    const b = operand();
    return cmpOperands(a, b, op);
  };
  const term = (): boolean => {
    let v = factor();
    while (peek()?.t === 'kw' && peek()!.v === 'AND') {
      next();
      v = factor() && v;
    }
    return v;
  };
  const expr = (): boolean => {
    let v = term();
    while (peek()?.t === 'kw' && peek()!.v === 'OR') {
      next();
      v = term() || v;
    }
    return v;
  };
  const result = expr();
  if (pos < toks.length) {
    throw new Error(`unexpected trailing "${toks[pos].v}"`);
  }
  return result;
}

/** Operand of an item read from memory, for conditions. */
export function operandOf(buf: Buffer, item: LayoutItem): Operand {
  const text = formatValue(buf, item);
  if (['display', 'comp3', 'binary', 'comp5', 'index'].includes(item.kind)) {
    const d = parseDecimal(text);
    if (d) {
      return { kind: 'number', value: d };
    }
  }
  return { kind: 'text', value: /^".*"$/s.test(text) ? unquote(text) : text };
}
