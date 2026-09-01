import type {
  ChatEventDataMap,
  ChatEventEnvelope,
  ChatEventName,
  Citation,
} from '../../../entities/chat/model/contracts';
import { chatRunReducer, createInitialChatRunState, type ChatRunState } from './chatReducer';
const CITATION: Citation = {
  id: 'C1',
  document_id: 'doc-1',
  title: 'Evidence title',
  translated_title: '证据标题',
  authors: ['Author'],
  year: 2024,
  source_url: 'https://example.org/evidence',
  evidence_tier: 'A',
  excerpt: 'Evidence excerpt',
  score: 0.91,
};
function envelope<EventName extends ChatEventName>(
  event: EventName,
  data: ChatEventDataMap[EventName],
  sequence: number,
): Extract<ChatEventEnvelope, { event: EventName }> {
  return {
    request_id: '11111111-1111-4111-8111-111111111111',
    session_id: '22222222-2222-4222-8222-222222222222',
    sequence,
    timestamp: '2026-08-26T00:00:00Z',
    event,
    data,
  } as unknown as Extract<ChatEventEnvelope, { event: EventName }>;
}
function apply(state: ChatRunState, event: ChatEventEnvelope): ChatRunState {
  return chatRunReducer(state, { type: 'event', envelope: event });
}
describe('chatRunReducer', () => {
  it('aggregates stream metadata, trace, sources, tokens, safety, and completion', () => {
    let state = chatRunReducer(createInitialChatRunState(), {
      type: 'start',
      sessionId: '22222222-2222-4222-8222-222222222222',
    });
    state = apply(
      state,
      envelope('meta', { stream_version: '1', trace_level: 'summary' }, 1),
    );
    state = apply(
      state,
      envelope(
        'status',
        { node: 'retrieve', status: 'completed', count: 3, duration_ms: 12.4 },
        2,
      ),
    );
    state = apply(state, envelope('sources', { citations: [CITATION] }, 3));
    state = apply(state, envelope('token', { content: '第一段' }, 4));
    state = apply(state, envelope('token', { content: '第二段' }, 5));
    state = apply(
      state,
      envelope('safety', { level: 'info', code: 'INSUFFICIENT_EVIDENCE' }, 6),
    );
    state = apply(
      state,
      envelope('safety', { level: 'info', code: 'INSUFFICIENT_EVIDENCE' }, 7),
    );
    state = apply(
      state,
      envelope('done', { finish_reason: 'insufficient_evidence', citation_count: 1 }, 8),
    );
    expect(state).toMatchObject({
      phase: 'done',
      answer: '第一段第二段',
      citations: [CITATION],
      finishReason: 'insufficient_evidence',
      lastSequence: 8,
    });
    expect(state.trace).toEqual([
      {
        node: 'retrieve',
        status: 'completed',
        count: 3,
        duration_ms: 12.4,
        sequence: 2,
      },
    ]);
    expect(state.safetyEvents).toHaveLength(1);
  });
  it('exposes only a sanitized server error and support id', () => {
    const state = apply(
      createInitialChatRunState(),
      envelope(
        'error',
        {
          code: 'CHAT_INTERNAL_ERROR',
          support_id: '33333333-3333-4333-8333-333333333333',
        },
        1,
      ),
    );
    expect(state.phase).toBe('error');
    expect(state.publicError).toEqual({
      code: 'CHAT_INTERNAL_ERROR',
      message: '问答服务未能完成本次请求。',
      supportId: '33333333-3333-4333-8333-333333333333',
    });
  });
  it('handles local failures, cancellation, and reset', () => {
    const failed = chatRunReducer(createInitialChatRunState(), {
      type: 'failed',
      error: { code: 'NETWORK_ERROR', message: '连接失败' },
    });
    expect(failed).toMatchObject({ phase: 'error', publicError: { code: 'NETWORK_ERROR' } });
    const cancelled = chatRunReducer(failed, { type: 'cancelled' });
    expect(cancelled.phase).toBe('cancelled');
    expect(chatRunReducer(cancelled, { type: 'reset' })).toEqual(createInitialChatRunState());
  });
});
