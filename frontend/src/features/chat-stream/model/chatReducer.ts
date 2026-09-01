import type {
  ChatEventEnvelope,
  ChatFinishReason,
  Citation,
  SafetyEventData,
  TraceEntry,
} from '../../../entities/chat/model/contracts';
export type ChatRunPhase =
  | 'idle'
  | 'connecting'
  | 'streaming'
  | 'done'
  | 'error'
  | 'cancelled';
export interface PublicChatError {
  code: string;
  message: string;
  supportId?: string;
}
export interface ChatRunState {
  phase: ChatRunPhase;
  sessionId: string | null;
  requestId: string | null;
  lastSequence: number;
  answer: string;
  citations: Citation[];
  trace: TraceEntry[];
  safetyEvents: SafetyEventData[];
  finishReason: ChatFinishReason | null;
  publicError: PublicChatError | null;
}
export type ChatRunAction =
  | { type: 'start'; sessionId: string }
  | { type: 'event'; envelope: ChatEventEnvelope }
  | { type: 'failed'; error: PublicChatError }
  | { type: 'cancelled' }
  | { type: 'reset' };
export function createInitialChatRunState(): ChatRunState {
  return {
    phase: 'idle',
    sessionId: null,
    requestId: null,
    lastSequence: 0,
    answer: '',
    citations: [],
    trace: [],
    safetyEvents: [],
    finishReason: null,
    publicError: null,
  };
}
export function chatRunReducer(state: ChatRunState, action: ChatRunAction): ChatRunState {
  if (action.type === 'reset') return createInitialChatRunState();
  if (action.type === 'start') {
    return {
      ...createInitialChatRunState(),
      phase: 'connecting',
      sessionId: action.sessionId,
    };
  }
  if (action.type === 'failed') {
    return { ...state, phase: 'error', publicError: action.error };
  }
  if (action.type === 'cancelled') {
    return { ...state, phase: 'cancelled' };
  }
  const { envelope } = action;
  const common = {
    ...state,
    phase: 'streaming' as const,
    requestId: envelope.request_id,
    lastSequence: envelope.sequence,
  };
  switch (envelope.event) {
    case 'meta':
      return common;
    case 'status':
      return {
        ...common,
        trace: [...state.trace, { ...envelope.data, sequence: envelope.sequence }],
      };
    case 'sources':
      return { ...common, citations: envelope.data.citations };
    case 'token':
      return { ...common, answer: state.answer + envelope.data.content };
    case 'safety':
      return state.safetyEvents.some((event) => event.code === envelope.data.code)
        ? common
        : { ...common, safetyEvents: [...state.safetyEvents, envelope.data] };
    case 'done':
      return {
        ...common,
        phase: 'done',
        finishReason: envelope.data.finish_reason,
      };
    case 'error':
      return {
        ...common,
        phase: 'error',
        publicError: {
          code: envelope.data.code,
          message: '问答服务未能完成本次请求。',
          supportId: envelope.data.support_id,
        },
      };
  }
}
