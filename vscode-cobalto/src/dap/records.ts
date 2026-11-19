// Reading COBOL data from the debugged process: where each 01 lives (its
// b_NNN static or LINKAGE parameter), its bytes, and the field a name and
// its subscripts point at. One memory read per record and stop.

import { Channel } from './channel';
import { ProgramMap } from './cobol-map';
import { LayoutItem, Located, offsetOf, Operand, operandOf, Reference } from './layout';
import { Session } from './session';

/** Bytes in the output of lldb's "memory read --format x --size 1": lines
 *  like "0x1000: 0x30 0x31 0x20", each with its address first. */
export function bytesOfMemoryRead(output: string): number[] {
  const bytes: number[] = [];
  for (const line of output.split(/\r?\n/)) {
    const colon = line.indexOf(':');
    if (colon < 0 || !/^\s*0x[0-9a-fA-F]+/.test(line)) {
      continue;
    }
    for (const m of line.slice(colon + 1).matchAll(/\b0x([0-9a-fA-F]{2})\b/g)) {
      bytes.push(parseInt(m[1], 16));
    }
  }
  return bytes;
}

export class Records {
  private readonly cache = new Map<string, Promise<Buffer | undefined>>();
  private readonly addresses = new Map<string, Promise<bigint | undefined>>();

  constructor(private readonly ch: Channel, private readonly session: Session) {}

  /** A new stop: the memory may have changed. */
  clear(): void {
    this.cache.clear();
    this.addresses.clear();
  }

  /** Forgets the bytes of one record (after writing to it). */
  forget(frameId: number, base: string): void {
    this.cache.delete(`${frameId}:${base}`);
  }

  /** Address of a b_NNN static or of a LINKAGE parameter in a frame. */
  baseAddress(frameId: number, base: string): Promise<bigint | undefined> {
    const key = `${frameId}:${base}`;
    let p = this.addresses.get(key);
    if (!p) {
      p = (async () => {
        try {
          const r = await this.ch.request('evaluate', { expression: `(unsigned long)${base}`, frameId, context: 'watch' });
          const m = r.success && typeof r.body?.result === 'string' ? /^(0x[0-9a-fA-F]+|\d+)/.exec(r.body.result.trim()) : null;
          if (!m) {
            return undefined;
          }
          const v = BigInt(m[1]);
          return v === 0n ? undefined : v;
        } catch {
          return undefined;
        }
      })();
      this.addresses.set(key, p);
    }
    return p;
  }

  /** Full bytes of a 01 (one memory read per record and stop). */
  readRecord(frameId: number, base: string, size: number): Promise<Buffer | undefined> {
    const key = `${frameId}:${base}`;
    let p = this.cache.get(key);
    if (!p) {
      p = (async () => {
        const addr = await this.baseAddress(frameId, base);
        if (addr === undefined || size <= 0) {
          return undefined;
        }
        try {
          return await this.readMemory(addr, size);
        } catch {
          return undefined;
        }
      })();
      this.cache.set(key, p);
    }
    return p;
  }

  /** Bytes of the debugged process. With an adapter that has no readMemory
   *  request, through the debugger's own command. */
  private async readMemory(addr: bigint, size: number): Promise<Buffer | undefined> {
    const at = '0x' + addr.toString(16);
    if (this.session.canReadMemory) {
      const r = await this.ch.request('readMemory', { memoryReference: at, count: size });
      return r.success && typeof r.body?.data === 'string' ? Buffer.from(r.body.data, 'base64') : undefined;
    }
    const r = await this.ch.request('evaluate', { expression: `\`memory read --force --format x --size 1 --count ${size} ${at}`, context: 'repl' });
    const bytes = r.success && typeof r.body?.result === 'string' ? bytesOfMemoryRead(r.body.result) : [];
    return bytes.length === size ? Buffer.from(bytes) : undefined;
  }

  /** Writes bytes to the debugged process; throws with the reason if it cannot. */
  async writeMemory(addr: bigint, bytes: Buffer): Promise<void> {
    const at = '0x' + addr.toString(16);
    if (this.session.canWriteMemory) {
      const r = await this.ch.request('writeMemory', { memoryReference: at, data: bytes.toString('base64') });
      if (!r.success) {
        throw new Error(r.message ?? 'writeMemory failed');
      }
      return;
    }
    const values = [...bytes].map((b) => '0x' + b.toString(16).padStart(2, '0')).join(' ');
    const r = await this.ch.request('evaluate', { expression: `\`memory write --size 1 ${at} ${values}`, context: 'repl' });
    const output = typeof r.body?.result === 'string' ? r.body.result : '';
    if (!r.success || /\berror:/i.test(output)) {
      throw new Error(r.message ?? (output.trim() || 'memory write failed'));
    }
  }

  /** Static (b_NNN) where a 01 of the layout lives, by name and section. */
  baseFor(map: ProgramMap, root: LayoutItem): string | undefined {
    for (const st of map.statics.values()) {
      if (st.internal || st.name.toUpperCase() !== root.name) {
        continue;
      }
      if ((root.section === 'LINKAGE') === !!st.linkage) {
        return st.id;
      }
    }
    return undefined;
  }

  /** Locates a reference (name and subscripts) in a program. */
  locate(program: string, ref: Reference): { loc: Located; base: string; offset: number } | undefined {
    const map = this.session.maps.get(program);
    const loc = this.session.layout?.find(program, ref.name);
    if (!map || !loc) {
      return undefined;
    }
    const base = this.baseFor(map, loc.root);
    if (!base) {
      return undefined;
    }
    const { offset, error } = offsetOf(loc, ref.subscripts);
    if (error) {
      throw new Error(error);
    }
    return { loc, base, offset };
  }

  async resolveNames(frameId: number, program: string, names: string[]): Promise<Map<string, Buffer | undefined>> {
    const out = new Map<string, Buffer | undefined>();
    for (const n of names) {
      const loc = this.session.layout?.find(program, n);
      const map = this.session.maps.get(program);
      const base = loc && map ? this.baseFor(map, loc.root) : undefined;
      if (loc && base && !out.has(base)) {
        out.set(base, await this.readRecord(frameId, base, loc.root.size * (loc.root.occurs || 1)));
      }
    }
    return out;
  }

  /** Operand of a condition: the field with that name in the program of the
   *  frame, read from the records resolveNames brought. */
  operandFor(program: string, records: Map<string, Buffer | undefined>, ref: Reference): Operand | undefined {
    const map = this.session.maps.get(program);
    const loc = this.session.layout?.find(program, ref.name);
    const base = loc && map ? this.baseFor(map, loc.root) : undefined;
    if (!loc || !base || !records.has(base)) {
      return undefined;
    }
    const buf = records.get(base);
    if (!buf) {
      throw new Error(`${ref.name}: the record could not be read`);
    }
    const { offset, error } = offsetOf(loc, ref.subscripts);
    if (error) {
      throw new Error(error);
    }
    return operandOf(buf.subarray(offset, offset + loc.item.size), loc.item);
  }
}
