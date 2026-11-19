// Unit tests for src/dap/protocol.ts: DAP framing.

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { DapMessage, DapReader, encode } from '../../dap/protocol';

const STOPPED: DapMessage = { seq: 7, type: 'event', event: 'stopped', body: { reason: 'breakpoint', threadId: 1 } };
const NEXT: DapMessage = { seq: 8, type: 'request', command: 'next', arguments: { threadId: 1 } };
const ACCENTED: DapMessage = { seq: 9, type: 'event', event: 'output', body: { output: 'Größe geändert: über 2000 – ¥ €' } };

function reader(): { feed: (chunk: Buffer) => void; received: DapMessage[] } {
  const received: DapMessage[] = [];
  const r = new DapReader((m) => received.push(m));
  return { feed: (chunk) => r.feed(chunk), received };
}

function frame(header: string, body: string): Buffer {
  return Buffer.concat([Buffer.from(header, 'ascii'), Buffer.from(body, 'utf8')]);
}

describe('encode', () => {
  test('the header announces the length of the body and the body is the JSON of the message', () => {
    const buf = encode(STOPPED);
    const split = buf.indexOf('\r\n\r\n');
    const body = buf.subarray(split + 4);
    assert.equal(buf.subarray(0, split).toString('ascii'), `Content-Length: ${body.length}`);
    assert.deepEqual(JSON.parse(body.toString('utf8')), STOPPED);
  });

  test('the length counts bytes, not characters', () => {
    const buf = encode(ACCENTED);
    const split = buf.indexOf('\r\n\r\n');
    const announced = Number(/Content-Length: (\d+)/.exec(buf.subarray(0, split).toString('ascii'))?.[1]);
    assert.equal(announced, buf.length - split - 4);
    assert.ok(announced > JSON.stringify(ACCENTED).length);
  });
});

describe('DapReader', () => {
  test('a whole message in one chunk is delivered', () => {
    const { feed, received } = reader();
    feed(encode(STOPPED));
    assert.deepEqual(received, [STOPPED]);
  });

  test('two messages in one chunk are delivered in order', () => {
    const { feed, received } = reader();
    feed(Buffer.concat([encode(STOPPED), encode(NEXT)]));
    assert.deepEqual(received, [STOPPED, NEXT]);
  });

  test('a message split in the middle of its body is delivered once it is complete', () => {
    const { feed, received } = reader();
    const buf = encode(STOPPED);
    feed(buf.subarray(0, buf.length - 10));
    assert.deepEqual(received, []);
    feed(buf.subarray(buf.length - 10));
    assert.deepEqual(received, [STOPPED]);
  });

  test('a message split in the middle of its header is delivered once it is complete', () => {
    const { feed, received } = reader();
    const buf = encode(STOPPED);
    feed(buf.subarray(0, 9));
    assert.deepEqual(received, []);
    feed(buf.subarray(9));
    assert.deepEqual(received, [STOPPED]);
  });

  test('messages that arrive byte by byte are each delivered once', () => {
    const { feed, received } = reader();
    const buf = Buffer.concat([encode(STOPPED), encode(NEXT)]);
    for (let i = 0; i < buf.length; i++) {
      feed(buf.subarray(i, i + 1));
    }
    assert.deepEqual(received, [STOPPED, NEXT]);
  });

  test('a chunk with one message and the start of another delivers the first and waits for the rest', () => {
    const { feed, received } = reader();
    const second = encode(NEXT);
    feed(Buffer.concat([encode(STOPPED), second.subarray(0, 25)]));
    assert.deepEqual(received, [STOPPED]);
    feed(second.subarray(25));
    assert.deepEqual(received, [STOPPED, NEXT]);
  });

  test('a character of several bytes split between chunks is read whole', () => {
    const { feed, received } = reader();
    const buf = encode(ACCENTED);
    const cut = buf.indexOf(Buffer.from('ö', 'utf8')) + 1;
    feed(buf.subarray(0, cut));
    feed(buf.subarray(cut));
    assert.deepEqual(received, [ACCENTED]);
  });

  test('other header fields next to Content-Length are accepted', () => {
    const { feed, received } = reader();
    const body = JSON.stringify(STOPPED);
    feed(frame(`Content-Length: ${Buffer.byteLength(body)}\r\nContent-Type: application/vscode-jsonrpc; charset=utf-8\r\n\r\n`, body));
    assert.deepEqual(received, [STOPPED]);
  });

  test('a body that is not JSON is dropped and the next message is still delivered', () => {
    const { feed, received } = reader();
    const garbage = '{"seq": 1, "type": ';
    feed(Buffer.concat([frame(`Content-Length: ${garbage.length}\r\n\r\n`, garbage), encode(NEXT)]));
    assert.deepEqual(received, [NEXT]);
  });

  test('a header block without Content-Length is skipped', () => {
    const { feed, received } = reader();
    feed(Buffer.concat([Buffer.from('X-Banner: lldb-dap ready\r\n\r\n', 'ascii'), encode(STOPPED)]));
    assert.deepEqual(received, [STOPPED]);
  });

  test('nothing is delivered for an empty chunk', () => {
    const { feed, received } = reader();
    feed(Buffer.alloc(0));
    assert.deepEqual(received, []);
  });
});
