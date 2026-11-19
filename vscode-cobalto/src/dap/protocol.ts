// Debug Adapter Protocol (DAP) framing: JSON messages preceded by
// "Content-Length: N\r\n\r\n". No dependencies.

export interface DapMessage {
  seq: number;
  type: 'request' | 'response' | 'event';
  [key: string]: unknown;
}

export interface DapRequest extends DapMessage {
  type: 'request';
  command: string;
  arguments?: Record<string, unknown>;
}

export interface DapResponse extends DapMessage {
  type: 'response';
  request_seq: number;
  success: boolean;
  command: string;
  message?: string;
  body?: Record<string, unknown>;
}

export interface DapEvent extends DapMessage {
  type: 'event';
  event: string;
  body?: Record<string, unknown>;
}

export function encode(msg: DapMessage): Buffer {
  const body = Buffer.from(JSON.stringify(msg), 'utf8');
  return Buffer.concat([Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, 'ascii'), body]);
}

/** Accumulates bytes and delivers complete messages. */
export class DapReader {
  private buffer = Buffer.alloc(0);
  private expected = -1;

  constructor(private readonly onMessage: (msg: DapMessage) => void) {}

  feed(chunk: Buffer): void {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    for (;;) {
      if (this.expected < 0) {
        const end = this.buffer.indexOf('\r\n\r\n');
        if (end < 0) {
          return;
        }
        const header = this.buffer.subarray(0, end).toString('ascii');
        const m = /Content-Length:\s*(\d+)/i.exec(header);
        if (!m) {
          this.buffer = this.buffer.subarray(end + 4);
          continue;
        }
        this.expected = parseInt(m[1], 10);
        this.buffer = this.buffer.subarray(end + 4);
      }
      if (this.buffer.length < this.expected) {
        return;
      }
      const body = this.buffer.subarray(0, this.expected).toString('utf8');
      this.buffer = this.buffer.subarray(this.expected);
      this.expected = -1;
      let msg: DapMessage | undefined;
      try {
        msg = JSON.parse(body) as DapMessage;
      } catch {
        msg = undefined;
      }
      if (msg) {
        this.onMessage(msg);
      }
    }
  }
}
