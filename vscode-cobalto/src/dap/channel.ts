// The two connections of the proxy: the client (VS Code or a script) and
// lldb-dap, which it starts on the first message. It sends and answers
// messages, pairs the proxy's own requests with their responses and hands
// the adapter's events to whoever created it.

import { ChildProcess, spawn } from 'child_process';
import { DapEvent, DapMessage, DapReader, DapRequest, DapResponse, encode } from './protocol';
import { ProxyOptions } from './session';

type Pending = { resolve: (r: DapResponse) => void; reject: (e: Error) => void };

export class Channel {
  private adapter?: ChildProcess;
  private readonly reader: DapReader;
  private mySeq = 100_000_000;
  private outSeq = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly clientTransforms = new Map<number, (r: DapResponse) => Promise<void> | void>();
  private disposed = false;

  constructor(
    private readonly toClient: (msg: DapMessage) => void,
    private readonly opts: ProxyOptions,
    private readonly onEvent: (ev: DapEvent) => void,
  ) {
    this.reader = new DapReader((m) => this.onAdapterMessage(m));
  }

  log(s: string): void {
    this.opts.log?.(s);
  }

  trace(dir: string, msg: DapMessage): void {
    if (this.opts.trace) {
      this.log(`${dir} ${JSON.stringify(msg)}`);
    }
  }

  private ensureAdapter(): void {
    if (this.adapter) {
      return;
    }
    this.log(`lldb-dap: ${this.opts.lldbDapPath} ${(this.opts.lldbDapArgs ?? []).join(' ')}`);
    const child = spawn(this.opts.lldbDapPath, this.opts.lldbDapArgs ?? [], { stdio: ['pipe', 'pipe', 'pipe'] });
    this.adapter = child;
    child.stdout.on('data', (c: Buffer) => this.reader.feed(c));
    child.stderr.on('data', (c: Buffer) => this.log(`lldb-dap stderr: ${c.toString().trimEnd()}`));
    child.on('error', (e) => {
      this.log(`could not run lldb-dap: ${e.message}`);
      this.sendEvent('output', { category: 'stderr', output: `Cobalto: could not run lldb-dap (${this.opts.lldbDapPath}): ${e.message}\n` });
      this.sendEvent('terminated', {});
    });
    child.on('exit', (code, signal) => {
      this.log(`lldb-dap exited (code=${code} signal=${signal})`);
      for (const p of this.pending.values()) {
        p.reject(new Error('lldb-dap exited'));
      }
      this.pending.clear();
      if (!this.disposed) {
        this.sendEvent('terminated', {});
      }
    });
  }

  toAdapter(msg: DapMessage): void {
    this.ensureAdapter();
    this.trace('->lldb', msg);
    this.adapter?.stdin?.write(encode(msg));
  }

  send(msg: DapMessage): void {
    this.trace('->client', msg);
    this.toClient(msg);
  }

  sendEvent(event: string, body: Record<string, unknown>): void {
    this.send({ seq: this.outSeq++, type: 'event', event, body } as DapEvent);
  }

  /** The proxy's own request to the adapter. */
  request(command: string, args: Record<string, unknown>): Promise<DapResponse> {
    const seq = this.mySeq++;
    return new Promise<DapResponse>((resolve, reject) => {
      this.pending.set(seq, { resolve, reject });
      this.toAdapter({ seq, type: 'request', command, arguments: args } as DapRequest);
    });
  }

  reply(req: DapRequest, body: Record<string, unknown>): void {
    this.send({ seq: this.outSeq++, type: 'response', request_seq: req.seq, success: true, command: req.command, body } as DapResponse);
  }

  replyWith(req: DapRequest, resp: DapResponse): void {
    this.send({ ...resp, seq: this.outSeq++, request_seq: req.seq, command: req.command });
  }

  forwardThen(req: DapRequest, transform: (r: DapResponse) => Promise<void> | void): void {
    this.clientTransforms.set(req.seq, transform);
    this.toAdapter(req);
  }

  fail(req: DapRequest, message: string): void {
    this.send({ seq: this.outSeq++, type: 'response', request_seq: req.seq, success: false, command: req.command, message } as DapResponse);
  }

  dispose(): void {
    this.disposed = true;
    if (this.adapter && !this.adapter.killed) {
      this.adapter.kill();
    }
    this.adapter = undefined;
  }

  private onAdapterMessage(msg: DapMessage): void {
    this.trace('<-lldb', msg);
    if (msg.type === 'response') {
      const r = msg as DapResponse;
      const mine = this.pending.get(r.request_seq);
      if (mine) {
        this.pending.delete(r.request_seq);
        mine.resolve(r);
        return;
      }
      const transform = this.clientTransforms.get(r.request_seq);
      if (transform) {
        this.clientTransforms.delete(r.request_seq);
        Promise.resolve(transform(r))
          .catch((e) => this.log(`transform of ${r.command} failed: ${String(e)}`))
          .then(() => this.send(r));
        return;
      }
      this.send(r);
      return;
    }
    if (msg.type === 'event') {
      this.onEvent(msg as DapEvent);
      return;
    }
    this.send(msg);
  }
}
