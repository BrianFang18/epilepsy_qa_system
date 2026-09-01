import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import type {
  ChatEventDataMap,
  ChatEventEnvelope,
  ChatEventName,
  ChatRequest,
} from '../../../entities/chat/model/contracts';
import {
  ChatProtocolError,
  type ChatTerminal,
  type StreamChatOptions,
} from '../api/streamChat';
import type { ChatRunState } from './chatReducer';
import { useChatStream } from './useChatStream';
const REQUEST: ChatRequest = {
  session_id: '22222222-2222-4222-8222-222222222222',
  message: '测试问题',
  history: [],
  trace_level: 'summary',
};
function envelope<EventName extends ChatEventName>(
  event: EventName,
  data: ChatEventDataMap[EventName],
  sequence: number,
): Extract<ChatEventEnvelope, { event: EventName }> {
  return {
    request_id: '11111111-1111-4111-8111-111111111111',
    session_id: REQUEST.session_id,
    sequence,
    timestamp: '2026-08-26T00:00:00Z',
    event,
    data,
  } as unknown as Extract<ChatEventEnvelope, { event: EventName }>;
}
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}
function emitSuccessfulStream(onEvent: (event: ChatEventEnvelope) => void): 'done' {
  onEvent(envelope('meta', { stream_version: '1', trace_level: 'summary' }, 1));
  onEvent(envelope('sources', { citations: [] }, 2));
  onEvent(envelope('token', { content: '完整回答' }, 3));
  onEvent(envelope('done', { finish_reason: 'stop', citation_count: 0 }, 4));
  return 'done';
}
const mockedStreamChat =
  vi.fn<(request: ChatRequest, options: StreamChatOptions) => Promise<ChatTerminal>>();
describe('useChatStream', () => {
  beforeEach(() => {
    mockedStreamChat.mockReset();
  });
  it('streams a successful answer and clears retry data on reset', async () => {
    mockedStreamChat.mockImplementation(async (_request, streamOptions) =>
      emitSuccessfulStream(streamOptions.onEvent),
    );
    const { result } = renderHook(() => useChatStream(mockedStreamChat), {
      wrapper: createWrapper(),
    });
    let finalState: ChatRunState | null = null;
    await act(async () => {
      finalState = await result.current.send(REQUEST);
    });
    expect(finalState).toMatchObject({ phase: 'done', answer: '完整回答' });
    expect(mockedStreamChat.mock.calls.map((call) => call.length)).toEqual([2]);
    expect(result.current.state).toMatchObject({ phase: 'done', answer: '完整回答' });
    expect(result.current.canRetry).toBe(true);
    act(() => result.current.reset());
    expect(result.current.state.phase).toBe('idle');
    expect(result.current.canRetry).toBe(false);
  });
  it('maps protocol failures to a sanitized public error and rethrows', async () => {
    mockedStreamChat.mockRejectedValue(new ChatProtocolError('协议错误'));
    const { result } = renderHook(() => useChatStream(mockedStreamChat), {
      wrapper: createWrapper(),
    });
    await act(async () => {
      await expect(result.current.send(REQUEST)).rejects.toThrow('协议错误');
    });
    expect(result.current.state).toMatchObject({
      phase: 'error',
      publicError: { code: 'STREAM_PROTOCOL_ERROR', message: '协议错误' },
    });
  });
  it('marks an active request as cancelled', async () => {
    mockedStreamChat.mockImplementation(
      (_request, streamOptions) =>
        new Promise((_resolve, reject) => {
          streamOptions.signal.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          );
        }),
    );
    const { result } = renderHook(() => useChatStream(mockedStreamChat), {
      wrapper: createWrapper(),
    });
    let pending: Promise<ChatRunState | null>;
    act(() => {
      pending = result.current.send(REQUEST);
    });
    await waitFor(() => expect(result.current.isRunning).toBe(true));
    act(() => result.current.cancel());
    await act(async () => expect(pending).resolves.toBeNull());
    expect(result.current.state.phase).toBe('cancelled');
    expect(result.current.canRetry).toBe(true);
  });
  it('keeps reset state after aborting and discards the private retry request', async () => {
    mockedStreamChat.mockImplementation(
      (_request, streamOptions) =>
        new Promise((_resolve, reject) => {
          streamOptions.signal.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          );
        }),
    );
    const { result } = renderHook(() => useChatStream(mockedStreamChat), {
      wrapper: createWrapper(),
    });
    let pending: Promise<ChatRunState | null>;
    act(() => {
      pending = result.current.send(REQUEST);
    });
    await waitFor(() => expect(result.current.isRunning).toBe(true));
    act(() => result.current.reset());
    await act(async () => expect(pending).resolves.toBeNull());
    expect(result.current.state.phase).toBe('idle');
    expect(result.current.canRetry).toBe(false);
  });
  it('ignores cancellation from an obsolete run after a newer run starts', async () => {
    let invocation = 0;
    mockedStreamChat.mockImplementation((_request, streamOptions) => {
      invocation += 1;
      if (invocation === 1) {
        return new Promise((_resolve, reject) => {
          streamOptions.signal.addEventListener(
            'abort',
            () => queueMicrotask(() => reject(new DOMException('aborted', 'AbortError'))),
            { once: true },
          );
        });
      }
      return Promise.resolve(emitSuccessfulStream(streamOptions.onEvent));
    });
    const { result } = renderHook(() => useChatStream(mockedStreamChat), {
      wrapper: createWrapper(),
    });
    let first: Promise<ChatRunState | null>;
    act(() => {
      first = result.current.send(REQUEST);
    });
    await waitFor(() => expect(mockedStreamChat).toHaveBeenCalledTimes(1));
    await act(async () => {
      const second = result.current.send({ ...REQUEST, message: '新问题' });
      await expect(second).resolves.toMatchObject({ phase: 'done' });
      await expect(first).resolves.toBeNull();
    });
    expect(result.current.state).toMatchObject({ phase: 'done', answer: '完整回答' });
  });
});
