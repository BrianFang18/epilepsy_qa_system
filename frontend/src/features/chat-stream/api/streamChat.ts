import {
  isKnownChatEventName,
  parseChatEnvelope,
  type ChatEventEnvelope,
  type ChatRequest,
  type UnknownChatEventEnvelope,
} from '../../../entities/chat/model/contracts';
import { apiErrorFromResponse } from '../../../shared/api/apiError';
import { readSseStream } from '../../../shared/api/sse';
import { API_ENDPOINTS } from '../../../shared/config/endpoints';

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export class ChatProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChatProtocolError';
  }
}

export interface StreamChatOptions {
  signal: AbortSignal;
  onEvent: (event: ChatEventEnvelope) => void;
  onUnknownEvent?: (event: UnknownChatEventEnvelope) => void;
  fetcher?: typeof fetch;
}

export type ChatTerminal = 'done' | 'error';

export async function streamChat(
  request: ChatRequest,
  options: StreamChatOptions,
): Promise<ChatTerminal> {
  const fetcher = options.fetcher ?? fetch;
  const response = await fetcher(API_ENDPOINTS.chatStream, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
    signal: options.signal,
  });

  if (!response.ok) throw await apiErrorFromResponse(response);
  if (!response.headers.get('content-type')?.toLowerCase().includes('text/event-stream')) {
    throw new ChatProtocolError('服务返回了非 SSE 响应。');
  }
  if (!response.body) throw new ChatProtocolError('浏览器未收到可读取的响应流。');

  let expectedSequence = 1;
  let requestId: string | null = null;
  let sourcesReceived = false;
  let terminal: ChatTerminal | null = null;

  for await (const rawEvent of readSseStream(response.body, options.signal)) {
    const envelope = parseChatEnvelope(rawEvent.data);

    if (rawEvent.event && rawEvent.event !== envelope.event) {
      throw new ChatProtocolError('SSE event 名称与数据不一致。');
    }
    if (rawEvent.id !== `${envelope.request_id}:${envelope.sequence}`) {
      throw new ChatProtocolError('SSE event ID 不合法。');
    }
    if (!UUID_PATTERN.test(envelope.request_id)) {
      throw new ChatProtocolError('SSE request_id 不是合法 UUID。');
    }
    if (envelope.session_id.toLowerCase() !== request.session_id.toLowerCase()) {
      throw new ChatProtocolError('SSE session_id 与请求不一致。');
    }
    if (envelope.sequence !== expectedSequence) {
      throw new ChatProtocolError('SSE sequence 不连续。');
    }
    if (Number.isNaN(Date.parse(envelope.timestamp))) {
      throw new ChatProtocolError('SSE timestamp 不合法。');
    }
    if (requestId !== null && requestId !== envelope.request_id) {
      throw new ChatProtocolError('同一响应中 request_id 发生变化。');
    }
    if (terminal !== null) {
      throw new ChatProtocolError('终止事件后仍收到额外数据。');
    }

    requestId = envelope.request_id;
    expectedSequence += 1;

    if (!isKnownChatEventName(envelope.event)) {
      options.onUnknownEvent?.(envelope);
      continue;
    }

    const knownEnvelope = envelope as ChatEventEnvelope;
    if (knownEnvelope.event === 'sources') sourcesReceived = true;
    if (knownEnvelope.event === 'token' && !sourcesReceived) {
      throw new ChatProtocolError('token 事件早于 sources 事件。');
    }

    options.onEvent(knownEnvelope);
    if (knownEnvelope.event === 'done') terminal = 'done';
    if (knownEnvelope.event === 'error') terminal = 'error';
  }

  if (options.signal.aborted) {
    throw options.signal.reason instanceof Error
      ? options.signal.reason
      : new DOMException('The operation was aborted', 'AbortError');
  }
  if (!terminal) throw new ChatProtocolError('SSE 流未发送终止事件。');
  return terminal;
}
