import type { ChatHistoryItem, StoredChatMessage } from '../../entities/chat/model/contracts';
export const SESSION_TTL_MS = 30 * 60 * 1000;
export const SESSION_STORAGE_KEY = 'epilepsy-qa.private-session.v1';
export const MAX_CHAT_MESSAGE_LENGTH = 4000;
const MAX_STORED_MESSAGES = 50;
const MAX_API_HISTORY = 12;
export interface PrivateChatSession {
  version: 1;
  sessionId: string;
  lastActivity: number;
  messages: StoredChatMessage[];
}
type SessionStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
function safeGetItem(storage: SessionStorage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}
function safeSetItem(storage: SessionStorage, key: string, value: string): void {
  try {
    storage.setItem(key, value);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
}
function safeRemoveItem(storage: SessionStorage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    // The in-memory React state remains usable when storage is unavailable.
  }
}
function isStoredMessage(value: unknown): value is StoredChatMessage {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<StoredChatMessage>;
  return (
    typeof candidate.id === 'string' &&
    (candidate.role === 'user' || candidate.role === 'assistant') &&
    typeof candidate.content === 'string' &&
    typeof candidate.createdAt === 'number'
  );
}
function parseSession(raw: string | null): PrivateChatSession | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<PrivateChatSession>;
    if (
      value.version !== 1 ||
      typeof value.sessionId !== 'string' ||
      typeof value.lastActivity !== 'number' ||
      !Array.isArray(value.messages) ||
      !value.messages.every(isStoredMessage)
    ) {
      return null;
    }
    return value as PrivateChatSession;
  } catch {
    return null;
  }
}
export function createPrivateSession(
  now = Date.now(),
  createId: () => string = () => crypto.randomUUID(),
): PrivateChatSession {
  return { version: 1, sessionId: createId(), lastActivity: now, messages: [] };
}
export function savePrivateSession(
  storage: SessionStorage,
  session: PrivateChatSession,
): void {
  const bounded = {
    ...session,
    messages: session.messages.slice(-MAX_STORED_MESSAGES),
  };
  safeSetItem(storage, SESSION_STORAGE_KEY, JSON.stringify(bounded));
}
export function loadOrCreatePrivateSession(
  storage: SessionStorage,
  now = Date.now(),
  createId: () => string = () => crypto.randomUUID(),
): PrivateChatSession {
  const existing = parseSession(safeGetItem(storage, SESSION_STORAGE_KEY));
  const expired =
    !existing ||
    existing.lastActivity > now + 60_000 ||
    now - existing.lastActivity >= SESSION_TTL_MS;
  if (!expired && existing) return existing;
  safeRemoveItem(storage, SESSION_STORAGE_KEY);
  const fresh = createPrivateSession(now, createId);
  savePrivateSession(storage, fresh);
  return fresh;
}
export function touchPrivateSession(
  storage: SessionStorage,
  session: PrivateChatSession,
  now = Date.now(),
): PrivateChatSession {
  const next = { ...session, lastActivity: now };
  savePrivateSession(storage, next);
  return next;
}
export function appendSessionMessage(
  storage: SessionStorage,
  session: PrivateChatSession,
  message: StoredChatMessage,
  now = Date.now(),
): PrivateChatSession {
  const next = {
    ...session,
    lastActivity: now,
    messages: [...session.messages, message].slice(-MAX_STORED_MESSAGES),
  };
  savePrivateSession(storage, next);
  return next;
}
export function clearPrivateSession(storage: SessionStorage): void {
  safeRemoveItem(storage, SESSION_STORAGE_KEY);
}
export function toApiHistory(messages: StoredChatMessage[]): ChatHistoryItem[] {
  return messages
    .filter((message) => message.content.trim().length > 0)
    .slice(-MAX_API_HISTORY)
    .map(({ role, content }) => ({
      role,
      content: content.slice(0, MAX_CHAT_MESSAGE_LENGTH),
    }));
}
