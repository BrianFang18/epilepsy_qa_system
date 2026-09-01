import type { StoredChatMessage } from '../../entities/chat/model/contracts';
import {
  MAX_CHAT_MESSAGE_LENGTH,
  SESSION_STORAGE_KEY,
  SESSION_TTL_MS,
  appendSessionMessage,
  clearPrivateSession,
  createPrivateSession,
  loadOrCreatePrivateSession,
  savePrivateSession,
  toApiHistory,
  touchPrivateSession,
} from './session';
type TestStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
function createStorage(): TestStorage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => void values.delete(key),
  };
}
function message(index: number, content = `message-${index}`): StoredChatMessage {
  return {
    id: `message-${index}`,
    role: index % 2 === 0 ? 'user' : 'assistant',
    content,
    createdAt: index,
  };
}
describe('private session storage', () => {
  it('creates, saves, loads, and touches an active session', () => {
    const storage = createStorage();
    const session = createPrivateSession(1_000, () => 'session-one');
    savePrivateSession(storage, session);
    expect(loadOrCreatePrivateSession(storage, 2_000, () => 'unused')).toEqual(session);
    expect(touchPrivateSession(storage, session, 3_000)).toMatchObject({
      sessionId: 'session-one',
      lastActivity: 3_000,
    });
  });
  it('rotates sessions at the TTL boundary and for future timestamps', () => {
    const storage = createStorage();
    savePrivateSession(
      storage,
      createPrivateSession(10_000, () => 'old'),
    );
    expect(
      loadOrCreatePrivateSession(storage, 10_000 + SESSION_TTL_MS, () => 'fresh'),
    ).toMatchObject({ sessionId: 'fresh', messages: [] });
    savePrivateSession(
      storage,
      createPrivateSession(200_001, () => 'future'),
    );
    expect(loadOrCreatePrivateSession(storage, 100_000, () => 'clock-reset')).toMatchObject({
      sessionId: 'clock-reset',
    });
  });
  it('replaces malformed persisted data', () => {
    const storage = createStorage();
    storage.setItem(SESSION_STORAGE_KEY, '{not-json');
    expect(loadOrCreatePrivateSession(storage, 500, () => 'replacement')).toMatchObject({
      sessionId: 'replacement',
      messages: [],
    });
  });
  it('keeps only the newest 50 local messages', () => {
    const storage = createStorage();
    let session = createPrivateSession(0, () => 'bounded');
    for (let index = 0; index < 55; index += 1) {
      session = appendSessionMessage(storage, session, message(index), index);
    }
    expect(session.messages).toHaveLength(50);
    expect(session.messages[0]?.id).toBe('message-5');
    expect(session.messages.at(-1)?.id).toBe('message-54');
  });
  it('sends only the newest 12 non-empty, bounded history entries', () => {
    const messages = [
      message(99, '   '),
      ...Array.from({ length: 14 }, (_, index) =>
        message(index, index === 13 ? 'x'.repeat(4_100) : `history-${index}`),
      ),
    ];
    const history = toApiHistory(messages);
    expect(history).toHaveLength(12);
    expect(history[0]?.content).toBe('history-2');
    expect(history.at(-1)?.content).toHaveLength(MAX_CHAT_MESSAGE_LENGTH);
  });
  it('continues in memory when browser storage is unavailable', () => {
    const unavailable: TestStorage = {
      getItem: () => {
        throw new DOMException('blocked', 'SecurityError');
      },
      setItem: () => {
        throw new DOMException('blocked', 'SecurityError');
      },
      removeItem: () => {
        throw new DOMException('blocked', 'SecurityError');
      },
    };
    expect(() => savePrivateSession(unavailable, createPrivateSession())).not.toThrow();
    expect(() => clearPrivateSession(unavailable)).not.toThrow();
    expect(loadOrCreatePrivateSession(unavailable, 1, () => 'memory')).toMatchObject({
      sessionId: 'memory',
    });
  });
});
