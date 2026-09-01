import { IncrementalSseParser, readSseStream } from './sse';
async function collectStream(stream: ReadableStream<Uint8Array>, signal: AbortSignal) {
  const events = [];
  for await (const event of readSseStream(stream, signal)) events.push(event);
  return events;
}
describe('IncrementalSseParser', () => {
  it('parses split CRLF frames, comments, ids, and multiline data', () => {
    const parser = new IncrementalSseParser();
    expect(parser.push(': keep-alive\r\nevent: token\r\nid: req:1\r\ndata: first')).toEqual(
      [],
    );
    expect(parser.push('\r\ndata: second\r\n\r\n')).toEqual([
      { event: 'token', id: 'req:1', data: 'first\nsecond' },
    ]);
  });
  it('flushes a final frame without a blank-line delimiter', () => {
    const parser = new IncrementalSseParser();
    parser.push('event: done\nid: req:2\ndata: {}');
    expect(parser.finish()).toEqual([{ event: 'done', id: 'req:2', data: '{}' }]);
    expect(parser.finish()).toEqual([]);
  });
  it('ignores frames without data fields and unsupported fields', () => {
    const parser = new IncrementalSseParser();
    expect(parser.push('event: ping\nretry: 1000\n\n')).toEqual([]);
  });
});
describe('readSseStream', () => {
  it('decodes multibyte text split across byte chunks', async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: 你好\n\n');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, bytes.length - 2));
        controller.enqueue(bytes.slice(bytes.length - 2));
        controller.close();
      },
    });
    await expect(collectStream(stream, new AbortController().signal)).resolves.toEqual([
      { event: 'token', data: '你好' },
    ]);
  });
  it('rejects immediately when the signal is already aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    const stream = new ReadableStream<Uint8Array>();
    await expect(collectStream(stream, controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    });
  });
});
