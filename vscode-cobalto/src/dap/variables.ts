// Variables as COBOL: the b_NNN statics of a frame shown with their COBOL
// name and their value formatted from the data layout, groups and OCCURS
// as children, evaluation of a name with subscripts, and writing a value
// back to memory.

import { Channel } from './channel';
import { CobolField, CobolStatic, ProgramMap } from './cobol-map';
import { encodeValue, formatValue, LayoutItem, parseReference } from './layout';
import { DapRequest, DapResponse } from './protocol';
import { Records } from './records';
import { Session } from './session';
import { Stack } from './stack';

interface SyntheticRef {
  frameId: number;
  map: ProgramMap;
  st: CobolStatic;
  originalRef: number;
  rawValue: string;
}

/** Variables panel node taken from the layout: a 01, a subfield, a whole
 *  OCCURS ("collection") or one of its occurrences ("element"). */
interface LayoutNode {
  frameId: number;
  program: string;
  /** static or C parameter where the 01 lives (b_NNN) */
  base: string;
  root: LayoutItem;
  item: LayoutItem;
  /** offset added by the occurrences already chosen */
  extra: number;
  mode: 'collection' | 'element';
  /** for a 01: the original lldb-dap variable (C bytes) */
  rawRef?: number;
  rawValue?: string;
}

const MAX_OCCURRENCES = 2000;

export class Variables {
  private readonly synthetic = new Map<number, SyntheticRef>();
  private readonly syntheticLists = new Map<number, Record<string, unknown>[]>();
  private readonly nodes = new Map<number, LayoutNode>();
  private nextSynthetic = 900_000_000;

  constructor(
    private readonly ch: Channel,
    private readonly session: Session,
    private readonly stack: Stack,
    private readonly records: Records,
  ) {}

  /** A new stop: the references handed out before are no longer valid. */
  clear(): void {
    this.synthetic.clear();
    this.syntheticLists.clear();
    this.nodes.clear();
  }

  private nodeValue(node: LayoutNode, buf: Buffer | undefined): string {
    if (node.mode === 'collection') {
      return `(${node.item.occurs} occurrences of ${node.item.size} bytes)`;
    }
    if (!buf) {
      return '(no data: the record could not be read)';
    }
    const start = node.item.offset + node.extra;
    const v = formatValue(buf.subarray(start, start + node.item.size), node.item);
    return v.length > 300 ? v.slice(0, 300) + '…' : v;
  }

  private nodeType(node: LayoutNode): string {
    const it = node.item;
    const pic = it.pic ? `PIC ${it.pic}` : it.kind === 'group' ? 'group' : it.kind;
    const usage = it.usage && it.usage !== 'DISPLAY' ? ` ${it.usage}` : '';
    const occ = it.occurs ? ` OCCURS ${it.occurs}` : '';
    return `${pic}${usage}${occ}, ${it.size} bytes, offset ${it.offset + node.extra}`;
  }

  private newNode(node: LayoutNode): number {
    const id = this.nextSynthetic++;
    this.nodes.set(id, node);
    return id;
  }

  private hasChildren(node: LayoutNode): boolean {
    return node.mode === 'collection' || node.item.children.length > 0 || node.rawRef !== undefined;
  }

  /** DAP variable of a node (with a reference to expand it when applicable). */
  private async nodeVariable(node: LayoutNode, name: string, buf: Buffer | undefined): Promise<Record<string, unknown>> {
    const v: Record<string, unknown> = {
      name,
      value: this.nodeValue(node, buf),
      type: this.nodeType(node),
      evaluateName: name,
      variablesReference: 0,
    };
    if (this.hasChildren(node)) {
      v.variablesReference = this.newNode(node);
      if (node.mode === 'collection') {
        v.indexedVariables = Math.min(node.item.occurs, MAX_OCCURRENCES);
      } else {
        v.namedVariables = node.item.children.length + (node.rawRef !== undefined ? 1 : 0);
      }
    }
    return v;
  }

  private async layoutChildren(node: LayoutNode): Promise<Record<string, unknown>[]> {
    const buf = await this.records.readRecord(node.frameId, node.base, node.root.size * (node.root.occurs || 1));
    const out: Record<string, unknown>[] = [];
    if (node.mode === 'collection') {
      const n = Math.min(node.item.occurs, MAX_OCCURRENCES);
      for (let k = 1; k <= n; k++) {
        const el: LayoutNode = { ...node, mode: 'element', extra: node.extra + (k - 1) * node.item.size, rawRef: undefined, rawValue: undefined };
        out.push(await this.nodeVariable(el, `${node.item.name}(${k})`, buf));
      }
      if (node.item.occurs > n) {
        out.push({ name: '…', value: `${node.item.occurs - n} more occurrences (use the console: ${node.item.name}(k))`, variablesReference: 0 });
      }
      return out;
    }
    for (const c of node.item.children) {
      const child: LayoutNode = { frameId: node.frameId, program: node.program, base: node.base, root: node.root, item: c, extra: node.extra, mode: c.occurs ? 'collection' : 'element' };
      out.push(await this.nodeVariable(child, c.name, buf));
    }
    if (node.rawRef !== undefined) {
      out.push({ name: `(C bytes: ${node.base})`, value: node.rawValue ?? '', type: `cob_u8_t[${node.root.size}]`, variablesReference: node.rawRef });
    }
    return out;
  }

  async onSetVariable(req: DapRequest): Promise<void> {
    const args = (req.arguments ?? {}) as { variablesReference: number; name: string; value: string };
    const node = this.nodes.get(args.variablesReference);
    let target: LayoutNode | undefined;
    if (node) {
      const children = node.mode === 'collection'
        ? undefined
        : node.item.children.map((c): LayoutNode => ({ frameId: node.frameId, program: node.program, base: node.base, root: node.root, item: c, extra: node.extra, mode: c.occurs ? 'collection' : 'element' }));
      if (node.mode === 'collection') {
        const m = /\((\d+)\)\s*$/.exec(args.name);
        const k = m ? parseInt(m[1], 10) : NaN;
        if (k >= 1 && k <= node.item.occurs) {
          target = { ...node, mode: 'element', extra: node.extra + (k - 1) * node.item.size, rawRef: undefined };
        }
      } else {
        target = children?.find((c) => c.item.name === args.name.toUpperCase());
      }
    } else {
      // reference of an lldb-dap scope: the name is a 01 of the frame's program
      const frameId = this.stack.scopeFrame.get(args.variablesReference);
      const info = frameId !== undefined ? this.stack.frames.get(frameId) : undefined;
      const map = info?.program ? this.session.maps.get(info.program) : undefined;
      const root = info?.program ? this.session.layout?.root(info.program, args.name) : undefined;
      const base = map && root ? this.records.baseFor(map, root) : undefined;
      if (frameId !== undefined && info?.program && root && base) {
        target = { frameId, program: info.program, base, root, item: root, extra: 0, mode: root.occurs ? 'collection' : 'element' };
      }
    }
    if (!target) {
      this.ch.toAdapter(req);
      return;
    }
    if (target.mode === 'collection') {
      this.ch.fail(req, `${target.item.name} is an OCCURS: change one occurrence (${target.item.name}(1))`);
      return;
    }
    try {
      const size = target.root.size * (target.root.occurs || 1);
      const buf = await this.records.readRecord(target.frameId, target.base, size);
      const addr = await this.records.baseAddress(target.frameId, target.base);
      if (!buf || addr === undefined) {
        throw new Error('the record could not be read');
      }
      const start = target.item.offset + target.extra;
      const bytes = encodeValue(args.value, target.item, buf.subarray(start, start + target.item.size));
      await this.records.writeMemory(addr + BigInt(start), bytes);
      this.records.forget(target.frameId, target.base);
      const after = await this.records.readRecord(target.frameId, target.base, size);
      this.ch.log(`setVariable ${target.item.name}+${start}: ${bytes.length} bytes`);
      this.ch.reply(req, { value: this.nodeValue(target, after), type: this.nodeType(target), variablesReference: 0 });
    } catch (e) {
      this.ch.fail(req, String(e instanceof Error ? e.message : e));
    }
  }

  private stripPointer(v: string): string {
    const m = /^0x[0-9a-fA-F]+\s+("[\s\S]*")$/.exec(v.trim());
    return m ? m[1] : v;
  }

  private async formatted(frameId: number, field: CobolField): Promise<string | undefined> {
    try {
      const r = await this.ch.request('evaluate', { expression: ProgramMap.valueExpression(field), frameId, context: 'watch' });
      if (!r.success || typeof r.body?.result !== 'string') {
        return undefined;
      }
      const v = this.stripPointer(r.body.result);
      return /^0x[0-9a-fA-F]+$/.test(v) ? undefined : v;
    } catch {
      return undefined;
    }
  }

  private describe(f: CobolField | undefined, id: string, size: number): string {
    return f ? `${f.field} / ${id}, ${size} bytes` : `${id}, ${size} bytes`;
  }

  async onVariables(req: DapRequest): Promise<void> {
    const args = (req.arguments ?? {}) as { variablesReference: number };
    const node = this.nodes.get(args.variablesReference);
    if (node) {
      try {
        this.ch.reply(req, { variables: await this.layoutChildren(node) });
      } catch (e) {
        this.ch.fail(req, String(e));
      }
      return;
    }
    const syn = this.synthetic.get(args.variablesReference);
    if (syn) {
      this.ch.reply(req, { variables: await this.syntheticChildren(syn) });
      return;
    }
    const list = this.syntheticLists.get(args.variablesReference);
    if (list) {
      this.ch.reply(req, { variables: list });
      return;
    }
    const frameId = this.stack.scopeFrame.get(args.variablesReference);
    let r: DapResponse;
    try {
      r = await this.ch.request('variables', req.arguments ?? {});
    } catch (e) {
      this.ch.fail(req, String(e));
      return;
    }
    const info = frameId !== undefined ? this.stack.frames.get(frameId) : undefined;
    const map = info?.program ? this.session.maps.get(info.program) : undefined;
    if (!r.success || !r.body || !map || frameId === undefined) {
      this.ch.replyWith(req, r);
      return;
    }
    const vars = (r.body.variables as Record<string, unknown>[]) ?? [];
    const mapped = vars.filter((v) => {
      const st = map.statics.get(String(v.name));
      return !!st && !st.internal;
    });
    if (!mapped.length) {
      this.ch.replyWith(req, r);
      return;
    }
    const doFormat = this.session.formatValues && mapped.length <= this.session.maxFormatted;
    let fromLayout = 0;
    await Promise.all(
      mapped.map(async (v) => {
        const st = map.statics.get(String(v.name))!;
        const raw = String(v.value ?? '');
        const root = this.session.layout?.root(map.program, st.name, st.linkage ? ['LINKAGE'] : ['WORKING-STORAGE', 'LOCAL-STORAGE', 'FILE']);
        if (root && this.session.formatValues) {
          const node: LayoutNode = { frameId, program: map.program, base: st.id, root, item: root, extra: 0, mode: root.occurs ? 'collection' : 'element', rawRef: Number(v.variablesReference ?? 0), rawValue: raw };
          const buf = await this.records.readRecord(frameId, st.id, root.size * (root.occurs || 1));
          if (buf) {
            const nv = await this.nodeVariable(node, st.name, buf);
            Object.assign(v, nv);
            delete v.indexedVariables;
            if (node.mode === 'collection') {
              v.indexedVariables = nv.indexedVariables;
              delete v.namedVariables;
            }
            fromLayout++;
            return;
          }
        }
        if (doFormat && st.field) {
          const val = await this.formatted(frameId, st.field);
          if (val !== undefined) {
            v.value = val;
          }
        } else if (!st.field) {
          v.value = this.stripPointer(raw);
        }
        v.name = st.name;
        v.evaluateName = st.name;
        v.type = this.describe(st.field, st.id, st.size);
        if (st.children.length) {
          const id = this.nextSynthetic++;
          this.synthetic.set(id, { frameId, map, st, originalRef: Number(v.variablesReference ?? 0), rawValue: raw });
          v.variablesReference = id;
          v.namedVariables = st.children.length + 1;
          delete v.indexedVariables;
        }
      }),
    );
    // what is not a COBOL field (module pointers, decimals, XML
    // records, frame_*) is grouped at the end
    const rest = vars.filter((v) => !mapped.includes(v));
    const shown = [...mapped];
    if (rest.length) {
      const id = this.nextSynthetic++;
      this.syntheticLists.set(id, rest);
      shown.push({ name: '(GnuCOBOL internals)', value: `${rest.length} items`, variablesReference: id, namedVariables: rest.length, presentationHint: { kind: 'virtual' } });
    }
    r.body.variables = shown;
    this.ch.log(`variables: ${mapped.length} fields of ${map.program} with COBOL names${doFormat ? ' and formatted values' : ''} (${fromLayout} from the layout), ${rest.length} internals grouped`);
    this.ch.replyWith(req, r);
  }

  private async syntheticChildren(syn: SyntheticRef): Promise<Record<string, unknown>[]> {
    const out: Record<string, unknown>[] = [];
    const doFormat = this.session.formatValues && syn.st.children.length <= this.session.maxFormatted;
    const values = await Promise.all(
      syn.st.children.map(async (f) => (doFormat ? await this.formatted(syn.frameId, f) : undefined)),
    );
    syn.st.children.forEach((f, i) => {
      out.push({
        name: f.name,
        value: values[i] ?? `(${f.size} bytes at ${f.base ?? '?'}+${f.offset})`,
        type: `${f.field}, ${f.size} bytes, offset ${f.offset}`,
        evaluateName: f.name,
        variablesReference: 0,
      });
    });
    out.push({
      name: `(C bytes: ${syn.st.id})`,
      value: syn.rawValue,
      type: `cob_u8_t[${syn.st.size}]`,
      variablesReference: syn.originalRef,
    });
    return out;
  }

  async onEvaluate(req: DapRequest): Promise<void> {
    const args = (req.arguments ?? {}) as { expression?: string; frameId?: number; context?: string };
    const expr = String(args.expression ?? '').trim();
    const info = args.frameId !== undefined ? this.stack.frames.get(args.frameId) : undefined;
    const map = info?.program ? this.session.maps.get(info.program) : undefined;
    const ref = parseReference(expr);
    if (ref && info?.program && args.frameId !== undefined && this.session.layout) {
      try {
        const found = this.records.locate(info.program, ref);
        if (found) {
          const node: LayoutNode = { frameId: args.frameId, program: info.program, base: found.base, root: found.loc.root, item: found.loc.item, extra: found.offset - found.loc.item.offset, mode: 'element' };
          const buf = await this.records.readRecord(args.frameId, found.base, found.loc.root.size * (found.loc.root.occurs || 1));
          if (buf) {
            const v = await this.nodeVariable(node, expr, buf);
            this.ch.reply(req, { result: v.value, type: `${found.loc.item.name} (${v.type})`, variablesReference: v.variablesReference, namedVariables: v.namedVariables });
            return;
          }
        }
      } catch (e) {
        this.ch.fail(req, String(e instanceof Error ? e.message : e));
        return;
      }
    }
    const field = map?.byName.get(ref ? ref.name : expr.toUpperCase());
    if (!field) {
      this.ch.toAdapter(req);
      return;
    }
    for (const expression of [ProgramMap.valueExpression(field), ProgramMap.rawExpression(field)]) {
      try {
        const r = await this.ch.request('evaluate', { ...args, expression, context: 'watch' });
        if (r.success && r.body && typeof r.body.result === 'string') {
          r.body.result = this.stripPointer(r.body.result);
          r.body.type = `${field.name} (${this.describe(field, field.base ?? 'LINKAGE', field.size)})`;
          r.body.variablesReference = 0;
          this.ch.replyWith(req, r);
          return;
        }
      } catch {
        /* next expression */
      }
    }
    this.ch.toAdapter(req);
  }
}
