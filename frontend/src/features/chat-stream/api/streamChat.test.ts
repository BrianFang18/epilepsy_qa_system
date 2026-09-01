import type {
  ChatEventEnvelope,
  ChatRequest,
  Citation,
  UnknownChatEventEnvelope,
} from '../../../entities/chat/model/contracts';
import { ChatProtocolError, streamChat } from './streamChat';
const SESSION_ID = '22222222-2222-4222-8222-222222222222';
const REQUEST_ID = '11111111-1111-4111-8111-111111111111';
const TIMESTAMP = '2026-08-26T00:00:00Z';
const REQUEST: ChatRequest = {
  session_id: SESSION_ID,
  message: '测试问题',
  history: [],
  trace_level: 'summary',
};
const CITATION: Citation = {
  id: 'C1',
  document_id: 'doc-1',
  title: 'Evidence',
  translated_title: null,
  authors: ['Author'],
  year: 2025,
  source_url: 'https://example.org',
  evidence_tier: 'A',
  excerpt: 'Excerpt',
  score: 0.9,
};
function frame(
  event: string,
  sequence: number,
  data: Record<string, unknown>,
  id = `${REQUEST_ID}:${sequence}`,
): string {
  const envelope = {
    request_id: REQUEST_ID,
    session_id: SESSION_ID,
    sequence,
    event,
    timestamp: TIMESTAMP,
    data,
  };
  return `event: ${event}\nid: ${id}\ndata: ${JSON.stringify(envelope)}\n\n`;
}
function sseResponse(chunks: string[], contentType = 'text/event-stream'): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { 'Content-Type': contentType } },
  );
}
function fetcherFor(response: Response): typeof fetch {
  return vi.fn(() => Promise.resolve(response)) as unknown as typeof fetch;
}
function options(
  response: Response,
  onEvent: (event: ChatEventEnvelope) => void = () => undefined,
  onUnknownEvent?: (event: UnknownChatEventEnvelope) => void,
) {
  return {
    signal: new AbortController().signal,
    onEvent,
    onUnknownEvent,
    fetcher: fetcherFor(response),
  };
}
describe('streamChat', () => {
  it('validates and emits a complete stream split across transport chunks', async () => {
    const payload =
      frame('meta', 1, { stream_version: '1', trace_level: 'summary' }) +
      frame('status', 2, {
        node: 'retrieve',
        status: 'completed',
        count: 1,
        duration_ms: 3,
      }) +
      frame('sources', 3, { citations: [CITATION] }) +
      frame('token', 4, { content: '回答' }) +
      frame('done', 5, { finish_reason: 'stop', citation_count: 1 });
    const events: ChatEventEnvelope[] = [];
    const response = sseResponse([
      payload.slice(0, 37),
      payload.slice(37, 143),
      payload.slice(143),
    ]);
    const streamOptions = options(response, (event) => events.push(event));
    await expect(streamChat(REQUEST, streamOptions)).resolves.toBe('done');
    expect(events.map((event) => event.event)).toEqual([
      'meta',
      'status',
      'sources',
      'token',
      'done',
    ]);
    expect(streamOptions.fetcher).toHaveBeenCalledWith(
      '/api/v1/chat/stream',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(REQUEST),
        signal: streamOptions.signal,
      }),
    );
  });
  it('forwards unknown events while preserving sequence validation', async () => {
    const unknown: UnknownChatEventEnvelope[] = [];
    const response = sseResponse([
      frame('meta', 1, { stream_version: '1', trace_level: 'summary' }),
      frame('heartbeat', 2, { version: 2 }),
      frame('sources', 3, { citations: [] }),
      frame('done', 4, { finish_reason: 'stop', citation_count: 0 }),
    ]);
    await expect(
      streamChat(
        REQUEST,
        options(response, undefined, (event) => unknown.push(event)),
      ),
    ).resolves.toBe('done');
    expect(unknown).toHaveLength(1);
    expect(unknown[0]?.event).toBe('heartbeat');
  });
  it('accepts a sanitized error as a terminal event', async () => {
    const events: ChatEventEnvelope[] = [];
    const response = sseResponse([
      frame('meta', 1, { stream_version: '1', trace_level: 'summary' }),
      frame('error', 2, {
        code: 'RETRIEVAL_UNAVAILABLE',
        support_id: '33333333-3333-4333-8333-333333333333',
      }),
    ]);
    await expect(
      streamChat(
        REQUEST,
        options(response, (event) => events.push(event)),
      ),
    ).resolves.toBe('error');
    expect(events.at(-1)?.event).toBe('error');
  });
  it('rejects tokens received before sources', async () => {
    const response = sseResponse([
      frame('meta', 1, { stream_version: '1', trace_level: 'summary' }),
      frame('token', 2, { content: 'unsafe order' }),
      frame('done', 3, { finish_reason: 'stop', citation_count: 0 }),
    ]);
    await expect(streamChat(REQUEST, options(response))).rejects.toThrow(
      'token 事件早于 sources 事件',
    );
  });
  it('rejects mismatched SSE ids and missing terminal events', async () => {
    const badId = sseResponse([
      frame('meta', 1, { stream_version: '1', trace_level: 'summary' }, 'wrong:1'),
    ]);
    await expect(streamChat(REQUEST, options(badId))).rejects.toBeInstanceOf(
      ChatProtocolError,
    );
    const missingTerminal = sseResponse([
      frame('meta', 1, { stream_version: '1', trace_level: 'summary' }),
      frame('sources', 2, { citations: [] }),
    ]);
    await expect(streamChat(REQUEST, options(missingTerminal))).rejects.toThrow(
      'SSE 流未发送终止事件',
    );
  });
  it('rejects non-SSE and non-success HTTP responses', async () => {
    await expect(
      streamChat(REQUEST, options(sseResponse(['{}'], 'application/json'))),
    ).rejects.toThrow('服务返回了非 SSE 响应');
    const httpError = new Response(JSON.stringify({ detail: { code: 'CHAT_NOT_READY' } }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
    await expect(streamChat(REQUEST, options(httpError))).rejects.toMatchObject({
      status: 503,
      code: 'CHAT_NOT_READY',
      message: '问答服务尚未就绪，请稍后重试。',
    });
  });
});
