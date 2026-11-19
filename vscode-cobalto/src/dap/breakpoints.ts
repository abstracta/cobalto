// Breakpoints set where the person reads: one in a .cblt or in the original
// program is moved to the generated source that actually gets compiled, and
// a condition written in COBOL is evaluated by the proxy when the breakpoint
// is hit.

import * as path from 'path';
import { Channel } from './channel';
import { conditionNames, evalCondition, looksLikeC } from './layout';
import { DapEvent, DapRequest } from './protocol';
import { Records } from './records';
import { Session } from './session';
import { Stack } from './stack';

interface Bp {
  line: number;
  condition?: string;
  hitCondition?: string;
  logMessage?: string;
}

export class Breakpoints {
  private readonly bpDirect = new Map<string, Bp[]>();
  private readonly bpMapped = new Map<string, Map<string, Map<number, Bp>>>();
  /** COBOL conditions per generated file (or direct source) and line */
  private readonly cobolConds = new Map<string, Map<number, string>>();
  /** breakpoint id in lldb-dap -> COBOL condition evaluated by the proxy */
  private readonly bpConditions = new Map<number, { condition: string; where: string }>();
  private suppressContinued = 0;

  constructor(
    private readonly ch: Channel,
    private readonly session: Session,
    private readonly stack: Stack,
    private readonly records: Records,
  ) {}

  /** Whether some breakpoint has a COBOL condition to evaluate on a stop. */
  get hasConditions(): boolean {
    return this.bpConditions.size > 0;
  }

  /** True for the "continued" that follows a stop the proxy resumed by
   *  itself because the condition was false: the client never saw the stop. */
  swallowContinued(): boolean {
    if (this.suppressContinued > 0) {
      this.suppressContinued--;
      return true;
    }
    return false;
  }

  async onSetBreakpoints(req: DapRequest): Promise<void> {
    const args = (req.arguments ?? {}) as { source?: { path?: string; name?: string }; breakpoints?: Bp[]; lines?: number[] };
    const srcPath = args.source?.path ? path.resolve(args.source.path) : undefined;
    const reqBps: Bp[] = args.breakpoints ?? (args.lines ?? []).map((line) => ({ line }));
    const lm = this.session.lineMap;
    if (!lm && srcPath && /\.cblt$/i.test(srcPath) && reqBps.length > 0) {
      // without a line map there is no way to move a breakpoint of the suite
      const message = this.session.suite
        ? `Cobalto: build/${this.session.suite}.lines.json is missing; run "cobalto debug --suite ${this.session.suite}" with the current version of the CLI.`
        : 'Cobalto: the configuration does not set "suite"; without it the .cblt breakpoints cannot be moved.';
      this.ch.log(`setBreakpoints ${path.basename(srcPath)}: no line map (${message})`);
      this.ch.reply(req, { breakpoints: reqBps.map((bp) => ({ verified: false, line: bp.line, source: args.source, message })) });
      return;
    }
    if (!lm || !srcPath) {
      this.ch.toAdapter(req);
      return;
    }
    try {
      if (lm.isGenerated(srcPath)) {
        // breakpoint set directly on build/<suite>.cbl: union with the moved ones
        this.bpDirect.set(srcPath, reqBps.map((bp) => this.splitCondition(srcPath, bp.line, bp)));
        const byLine = await this.sendGenerated(srcPath);
        const out = reqBps.map((bp) => byLine.get(bp.line) ?? { verified: false, line: bp.line });
        this.ch.reply(req, { breakpoints: out });
        return;
      }
      const gens = lm.generatedFor(srcPath);
      if (!gens) {
        this.ch.toAdapter(req);
        return;
      }
      // origin (.cblt or original program): move to each generated source
      const previous = this.bpMapped.get(srcPath);
      const mapped = new Map<string, Map<number, Bp>>();
      for (const [gen, lines] of gens) {
        for (const bp of reqBps) {
          const gl = lines.get(bp.line);
          if (gl !== undefined) {
            let m = mapped.get(gen);
            if (!m) {
              m = new Map();
              mapped.set(gen, m);
            }
            m.set(bp.line, this.splitCondition(gen, gl, { ...bp, line: gl }));
          }
        }
      }
      this.bpMapped.set(srcPath, mapped);
      const toSend = new Set<string>([...mapped.keys(), ...(previous ? previous.keys() : [])]);
      const results = new Map<string, Map<number, Record<string, unknown>>>();
      for (const gen of toSend) {
        results.set(gen, await this.sendGenerated(gen));
      }
      // if the origin is also compiled as is (src/X.cbl), keep its own breakpoints
      let base: Record<string, unknown>[] | undefined;
      if (!/\.cblt$/i.test(srcPath)) {
        const own = reqBps.map((bp) => this.splitCondition(srcPath, bp.line, bp));
        const r = await this.ch.request('setBreakpoints', { ...(req.arguments ?? {}), breakpoints: own, lines: own.map((b) => b.line) });
        base = r.success ? ((r.body?.breakpoints as Record<string, unknown>[]) ?? undefined) : undefined;
        this.rememberConditions(srcPath, own, base ?? []);
      }
      const out = reqBps.map((bp, i) => {
        const own = base?.[i];
        let verified = !!(own && own.verified);
        let message: string | undefined = own && typeof own.message === 'string' ? own.message : undefined;
        for (const [gen, m] of mapped) {
          const gl = m.get(bp.line)?.line;
          const r = gl !== undefined ? results.get(gen)?.get(gl) : undefined;
          if (r && r.verified) {
            verified = true;
            message = undefined;
          }
        }
        return { verified, line: bp.line, source: args.source, message };
      });
      this.ch.log(`setBreakpoints ${path.basename(srcPath)}: ${reqBps.map((b) => b.line).join(',')} -> ${[...mapped].map(([g, m]) => `${path.basename(g)}:${[...m.values()].map((b) => b.line).join(',')}`).join(' ')}`);
      this.ch.reply(req, { breakpoints: out });
    } catch (e) {
      this.ch.log(`setBreakpoints failed: ${String(e)}`);
      this.ch.toAdapter(req);
    }
  }

  /** Sends lldb-dap the union of breakpoints of a generated source. */
  private async sendGenerated(gen: string): Promise<Map<number, Record<string, unknown>>> {
    const union = new Map<number, Bp>();
    for (const bp of this.bpDirect.get(gen) ?? []) {
      union.set(bp.line, bp);
    }
    for (const byGen of this.bpMapped.values()) {
      for (const bp of byGen.get(gen)?.values() ?? []) {
        if (!union.has(bp.line)) {
          union.set(bp.line, bp);
        }
      }
    }
    const list = [...union.values()];
    const r = await this.ch.request('setBreakpoints', {
      source: { name: path.basename(gen), path: gen },
      breakpoints: list,
      lines: list.map((b) => b.line),
      sourceModified: false,
    });
    const byLine = new Map<number, Record<string, unknown>>();
    const got = r.success ? ((r.body?.breakpoints as Record<string, unknown>[]) ?? []) : [];
    list.forEach((bp, i) => {
      byLine.set(bp.line, got[i] ?? { verified: false, line: bp.line });
    });
    this.rememberConditions(gen, list, got);
    return byLine;
  }

  /** Separates a COBOL condition (evaluated by the proxy) from an lldb one (passed
   *  as is). It is COBOL if it mentions at least one name with letters and hyphens
   *  or a COBOL operator; a C expression (see looksLikeC) is left to lldb. */
  private splitCondition(file: string, line: number, bp: Bp): Bp {
    const conds = this.cobolConds.get(file) ?? new Map<number, string>();
    this.cobolConds.set(file, conds);
    conds.delete(line);
    const c = bp.condition?.trim();
    if (!c) {
      return bp;
    }
    const names = conditionNames(c);
    if (names.length && !looksLikeC(c) && this.session.layout) {
      conds.set(line, c);
      const { condition: _omit, ...rest } = bp;
      return rest;
    }
    return bp;
  }

  private rememberConditions(file: string, sent: Bp[], got: Record<string, unknown>[]): void {
    const conds = this.cobolConds.get(file);
    sent.forEach((bp, i) => {
      const id = got[i]?.id;
      const cond = conds?.get(bp.line);
      if (typeof id === 'number') {
        if (cond) {
          this.bpConditions.set(id, { condition: cond, where: `${path.basename(file)}:${bp.line}` });
        } else {
          this.bpConditions.delete(id);
        }
      }
    });
  }

  /** On a stop at a breakpoint with a COBOL condition: evaluates it in the top
   *  frame and, if it is false, resumes without telling the client. */
  async checkCondition(ev: DapEvent): Promise<void> {
    const body = (ev.body ?? {}) as { threadId?: number; hitBreakpointIds?: number[] };
    const hits = (body.hitBreakpointIds ?? []).map((id) => this.bpConditions.get(id)).filter((c): c is { condition: string; where: string } => !!c);
    if (!hits.length || body.threadId === undefined) {
      this.ch.send(ev);
      return;
    }
    let verdict = true;
    for (const h of hits) {
      try {
        const loc = await this.stack.topLocation(body.threadId);
        const frameId = loc?.id;
        const program = loc?.program;
        if (frameId === undefined || !program) {
          throw new Error('no COBOL program in the top frame');
        }
        const resolved = await this.records.resolveNames(frameId, program, conditionNames(h.condition));
        verdict = evalCondition(h.condition, (ref) => this.records.operandFor(program, resolved, ref));
        this.ch.log(`condition at ${h.where}: ${h.condition} -> ${verdict}`);
      } catch (e) {
        this.ch.log(`condition at ${h.where} could not be evaluated: ${String(e)}`);
        this.ch.sendEvent('output', { category: 'console', output: `Cobalto: the condition "${h.condition}" (${h.where}) could not be evaluated: ${String(e)}\n` });
        verdict = true;
      }
      if (!verdict) {
        break;
      }
    }
    if (verdict) {
      this.ch.send(ev);
      return;
    }
    this.suppressContinued++;
    try {
      await this.ch.request('continue', { threadId: body.threadId });
    } catch (e) {
      this.suppressContinued--;
      this.ch.log(`continue after a false condition failed: ${String(e)}`);
      this.ch.send(ev);
    }
  }
}
