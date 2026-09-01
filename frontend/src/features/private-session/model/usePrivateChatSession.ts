import { useCallback, useEffect, useRef, useState } from 'react';

import type { StoredChatMessage } from '../../../entities/chat/model/contracts';
import {
  SESSION_TTL_MS,
  appendSessionMessage,
  clearPrivateSession,
  createPrivateSession,
  loadOrCreatePrivateSession,
  savePrivateSession,
  touchPrivateSession,
  type PrivateChatSession,
} from '../../../shared/lib/session';

export function usePrivateChatSession() {
  const [session, setSession] = useState<PrivateChatSession>(() =>
    loadOrCreatePrivateSession(window.sessionStorage),
  );
  const sessionRef = useRef(session);
  const expiryRef = useRef<number | null>(null);
  sessionRef.current = session;

  const scheduleExpiry = useCallback((lastActivity: number) => {
    const schedule = (activity: number) => {
      if (expiryRef.current !== null) window.clearTimeout(expiryRef.current);
      const remaining = Math.max(activity + SESSION_TTL_MS - Date.now(), 0);
      expiryRef.current = window.setTimeout(() => {
        const current = sessionRef.current;
        if (Date.now() - current.lastActivity >= SESSION_TTL_MS) {
          clearPrivateSession(window.sessionStorage);
          const fresh = createPrivateSession();
          savePrivateSession(window.sessionStorage, fresh);
          setSession(fresh);
        } else {
          schedule(current.lastActivity);
        }
      }, remaining);
    };

    schedule(lastActivity);
  }, []);

  const touch = useCallback(() => {
    setSession((current) => {
      const next = touchPrivateSession(window.sessionStorage, current);
      scheduleExpiry(next.lastActivity);
      return next;
    });
  }, [scheduleExpiry]);

  const appendMessage = useCallback(
    (message: StoredChatMessage) => {
      setSession((current) => {
        const next = appendSessionMessage(window.sessionStorage, current, message);
        scheduleExpiry(next.lastActivity);
        return next;
      });
    },
    [scheduleExpiry],
  );

  const clear = useCallback(() => {
    clearPrivateSession(window.sessionStorage);
    const fresh = createPrivateSession();
    savePrivateSession(window.sessionStorage, fresh);
    setSession(fresh);
    scheduleExpiry(fresh.lastActivity);
  }, [scheduleExpiry]);

  useEffect(() => {
    scheduleExpiry(sessionRef.current.lastActivity);
    const onActivity = () => touch();
    window.addEventListener('pointerdown', onActivity, { passive: true });
    window.addEventListener('keydown', onActivity);
    window.addEventListener('focus', onActivity);
    return () => {
      if (expiryRef.current !== null) window.clearTimeout(expiryRef.current);
      window.removeEventListener('pointerdown', onActivity);
      window.removeEventListener('keydown', onActivity);
      window.removeEventListener('focus', onActivity);
    };
  }, [scheduleExpiry, touch]);

  return { session, appendMessage, clear, touch };
}
