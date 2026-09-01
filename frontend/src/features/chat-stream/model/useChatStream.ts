import { useMutation } from '@tanstack/react-query';
import { useCallback, useEffect, useReducer, useRef } from 'react';
import type { ChatRequest } from '../../../entities/chat/model/contracts';
import { ApiError, isAbortError } from '../../../shared/api/apiError';
import { ChatProtocolError, streamChat } from '../api/streamChat';
import {
  chatRunReducer,
  createInitialChatRunState,
  type ChatRunState,
  type PublicChatError,
} from './chatReducer';
interface MutationInput {
  request: ChatRequest;
  controller: AbortController;
  runId: symbol;
}
function publicErrorFrom(error: unknown): PublicChatError {
  if (error instanceof ApiError) {
    return {
      code: error.code,
      message: error.message,
      supportId: error.supportId,
    };
  }
  if (error instanceof ChatProtocolError) {
    return { code: 'STREAM_PROTOCOL_ERROR', message: error.message };
  }
  return {
    code: 'NETWORK_ERROR',
    message: '无法连接问答服务，请检查本地服务状态后重试。',
  };
}
export function useChatStream(streamChatFn: typeof streamChat = streamChat) {
  const [state, dispatch] = useReducer(chatRunReducer, undefined, createInitialChatRunState);
  const controllerRef = useRef<AbortController | null>(null);
  const activeRunRef = useRef<symbol | null>(null);
  const lastRequestRef = useRef<ChatRequest | null>(null);
  const { mutateAsync } = useMutation<ChatRunState, unknown, MutationInput>({
    retry: false,
    mutationFn: async ({ request, controller, runId }) => {
      let runState: ChatRunState = {
        ...createInitialChatRunState(),
        phase: 'connecting',
        sessionId: request.session_id,
      };
      await streamChatFn(request, {
        signal: controller.signal,
        onEvent: (envelope) => {
          runState = chatRunReducer(runState, { type: 'event', envelope });
          if (activeRunRef.current === runId) {
            dispatch({ type: 'event', envelope });
          }
        },
      });
      return runState;
    },
  });
  const send = useCallback(
    async (request: ChatRequest): Promise<ChatRunState | null> => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      const runId = Symbol('chat-run');
      controllerRef.current = controller;
      activeRunRef.current = runId;
      lastRequestRef.current = request;
      dispatch({ type: 'start', sessionId: request.session_id });
      try {
        return await mutateAsync({ request, controller, runId });
      } catch (error) {
        if (isAbortError(error)) {
          if (activeRunRef.current === runId) dispatch({ type: 'cancelled' });
          return null;
        }
        if (activeRunRef.current === runId) {
          dispatch({ type: 'failed', error: publicErrorFrom(error) });
        }
        throw error;
      } finally {
        if (activeRunRef.current === runId) activeRunRef.current = null;
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    },
    [mutateAsync],
  );
  const cancel = useCallback(() => controllerRef.current?.abort(), []);
  const retry = useCallback(
    () => (lastRequestRef.current ? send(lastRequestRef.current) : Promise.resolve(null)),
    [send],
  );
  const reset = useCallback(() => {
    activeRunRef.current = null;
    const controller = controllerRef.current;
    controllerRef.current = null;
    lastRequestRef.current = null;
    controller?.abort();
    dispatch({ type: 'reset' });
  }, []);
  useEffect(
    () => () => {
      activeRunRef.current = null;
      controllerRef.current?.abort();
    },
    [],
  );
  return {
    state,
    send,
    cancel,
    retry,
    reset,
    canRetry: lastRequestRef.current !== null,
    isRunning: state.phase === 'connecting' || state.phase === 'streaming',
  };
}
