export const CHAT_EVENT_NAMES = [
  'meta',
  'status',
  'sources',
  'token',
  'safety',
  'done',
  'error',
] as const;

export type ChatEventName = (typeof CHAT_EVENT_NAMES)[number];
export type EvidenceTier = 'A' | 'B' | 'C' | 'Unrated';
export type TraceStatus = 'completed' | 'skipped' | 'blocked';
export type ChatFinishReason = 'stop' | 'emergency' | 'insufficient_evidence';
export type ChatErrorCode =
  | 'RETRIEVAL_UNAVAILABLE'
  | 'LLM_UPSTREAM_UNAVAILABLE'
  | 'CHAT_INTERNAL_ERROR';

export interface ChatHistoryItem {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  session_id: string;
  message: string;
  history: ChatHistoryItem[];
  trace_level: 'summary';
}

export interface Citation {
  id: string;
  document_id: string;
  title: string;
  translated_title: string | null;
  authors: string[];
  year: number | null;
  source_url: string | null;
  evidence_tier: EvidenceTier;
  excerpt: string;
  score: number;
}

export interface TraceEntry {
  node: string;
  status: TraceStatus;
  count: number | null;
  duration_ms: number;
  sequence: number;
}

export type SafetyEventData =
  | {
      level: 'critical';
      code: 'EMERGENCY_DETECTED';
      categories: string[];
    }
  | { level: 'info'; code: 'INSUFFICIENT_EVIDENCE' }
  | {
      level: 'warning';
      code:
        | 'INVALID_CITATION_REMOVED'
        | 'DIRECT_DIAGNOSIS_BLOCKED'
        | 'INDIVIDUAL_MEDICATION_ADVICE_BLOCKED';
    };

export interface ChatEventDataMap {
  meta: { stream_version: string; trace_level: 'summary' | 'diagnostic' };
  status: Omit<TraceEntry, 'sequence'>;
  sources: { citations: Citation[] };
  token: { content: string };
  safety: SafetyEventData;
  done: {
    finish_reason: ChatFinishReason;
    citation_count: number;
    safety_adjustments?: number;
  };
  error: { code: ChatErrorCode; support_id: string };
}

interface ChatEnvelopeBase {
  request_id: string;
  session_id: string;
  sequence: number;
  timestamp: string;
}

export type ChatEventEnvelope = {
  [EventName in ChatEventName]: ChatEnvelopeBase & {
    event: EventName;
    data: ChatEventDataMap[EventName];
  };
}[ChatEventName];

export type UnknownChatEventEnvelope = ChatEnvelopeBase & {
  event: string;
  data: Record<string, unknown>;
};

export type ParsedChatEnvelope = ChatEventEnvelope | UnknownChatEventEnvelope;

export interface StoredChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: number;
  citations?: Citation[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasString(record: Record<string, unknown>, key: string): boolean {
  return typeof record[key] === 'string';
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isCitation(value: unknown): value is Citation {
  if (!isRecord(value)) return false;
  return (
    hasString(value, 'id') &&
    hasString(value, 'document_id') &&
    hasString(value, 'title') &&
    (value.translated_title === null || typeof value.translated_title === 'string') &&
    isStringArray(value.authors) &&
    (value.year === null || Number.isInteger(value.year)) &&
    (value.source_url === null || typeof value.source_url === 'string') &&
    (value.evidence_tier === 'A' ||
      value.evidence_tier === 'B' ||
      value.evidence_tier === 'C' ||
      value.evidence_tier === 'Unrated') &&
    typeof value.excerpt === 'string' &&
    typeof value.score === 'number' &&
    Number.isFinite(value.score)
  );
}

function isKnownEventData(event: ChatEventName, data: Record<string, unknown>): boolean {
  switch (event) {
    case 'meta':
      return (
        hasString(data, 'stream_version') &&
        (data.trace_level === 'summary' || data.trace_level === 'diagnostic')
      );
    case 'status':
      return (
        hasString(data, 'node') &&
        (data.status === 'completed' ||
          data.status === 'skipped' ||
          data.status === 'blocked') &&
        (data.count === null || isNonNegativeInteger(data.count)) &&
        typeof data.duration_ms === 'number' &&
        Number.isFinite(data.duration_ms) &&
        data.duration_ms >= 0
      );
    case 'sources':
      return Array.isArray(data.citations) && data.citations.every(isCitation);
    case 'token':
      return hasString(data, 'content');
    case 'safety':
      if (data.level === 'critical') {
        return data.code === 'EMERGENCY_DETECTED' && isStringArray(data.categories);
      }
      if (data.level === 'info') return data.code === 'INSUFFICIENT_EVIDENCE';
      return (
        data.level === 'warning' &&
        (data.code === 'INVALID_CITATION_REMOVED' ||
          data.code === 'DIRECT_DIAGNOSIS_BLOCKED' ||
          data.code === 'INDIVIDUAL_MEDICATION_ADVICE_BLOCKED')
      );
    case 'done':
      return (
        (data.finish_reason === 'stop' ||
          data.finish_reason === 'emergency' ||
          data.finish_reason === 'insufficient_evidence') &&
        isNonNegativeInteger(data.citation_count) &&
        (data.safety_adjustments === undefined ||
          isNonNegativeInteger(data.safety_adjustments))
      );
    case 'error':
      return (
        (data.code === 'RETRIEVAL_UNAVAILABLE' ||
          data.code === 'LLM_UPSTREAM_UNAVAILABLE' ||
          data.code === 'CHAT_INTERNAL_ERROR') &&
        hasString(data, 'support_id')
      );
  }
}

export function isKnownChatEventName(value: string): value is ChatEventName {
  return (CHAT_EVENT_NAMES as readonly string[]).includes(value);
}

export function parseChatEnvelope(serialized: string): ParsedChatEnvelope {
  let parsed: unknown;
  try {
    parsed = JSON.parse(serialized);
  } catch {
    throw new Error('SSE data is not valid JSON');
  }

  if (
    !isRecord(parsed) ||
    !hasString(parsed, 'request_id') ||
    !hasString(parsed, 'session_id') ||
    !hasString(parsed, 'event') ||
    !hasString(parsed, 'timestamp') ||
    !Number.isInteger(parsed.sequence) ||
    (parsed.sequence as number) < 1 ||
    !isRecord(parsed.data)
  ) {
    throw new Error('SSE envelope is malformed');
  }

  if (isKnownChatEventName(parsed.event as string)) {
    const event = parsed.event as ChatEventName;
    if (!isKnownEventData(event, parsed.data)) {
      throw new Error(`SSE ${event} event data is malformed`);
    }
    return parsed as unknown as ChatEventEnvelope;
  }

  return parsed as unknown as UnknownChatEventEnvelope;
}
