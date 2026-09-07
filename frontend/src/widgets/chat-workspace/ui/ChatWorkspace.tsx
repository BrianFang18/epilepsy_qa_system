import {
  DeleteOutlined,
  LoadingOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
} from '@ant-design/icons';
import Sender from '@ant-design/x/es/sender';
import { Alert, Badge, Button, Card, Empty, Popconfirm, Space, Tag, Typography } from 'antd';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import type { Citation, StoredChatMessage } from '../../../entities/chat/model/contracts';
import { CitationDrawer } from '../../../entities/chat/ui/LazyCitationDrawer';
import { MessageBubble } from '../../../entities/chat/ui/MessageBubble';
import { SafetyNotices } from '../../../entities/chat/ui/SafetyNotices';
import { TraceTimeline } from '../../../entities/chat/ui/TraceTimeline';
import { useBackendReadiness } from '../../../features/backend-health/model/useBackendReadiness';
import { useChatStream } from '../../../features/chat-stream/model/useChatStream';
import { usePrivateChatSession } from '../../../features/private-session/model/usePrivateChatSession';
import { MAX_CHAT_MESSAGE_LENGTH, toApiHistory } from '../../../shared/lib/session';
const SUGGESTED_QUESTIONS = [
  '癫痫发作时，家属应该如何进行现场急救？',
  '抗癫痫药物治疗中常见的注意事项有哪些？',
  '癫痫患者通常需要关注哪些生活方式因素？',
];
const PHASE_LABELS = {
  idle: '等待提问',
  connecting: '正在连接',
  streaming: '正在生成',
  done: '回答完成',
  error: '生成失败',
  cancelled: '已停止生成',
} as const;
export function ChatWorkspace() {
  const readiness = useBackendReadiness();
  const { session, appendMessage, clear } = usePrivateChatSession();
  const { state, send, cancel, retry, reset, canRetry, isRunning } = useChatStream();
  const [draft, setDraft] = useState('');
  const [validationMessage, setValidationMessage] = useState<string | null>(null);
  const [selectedCitations, setSelectedCitations] = useState<readonly Citation[]>([]);
  const [citationDrawerOpen, setCitationDrawerOpen] = useState(false);
  const [answerPersisted, setAnswerPersisted] = useState(false);
  const senderRef = useRef<ComponentRef<typeof Sender>>(null);
  const messageEndRef = useRef<HTMLDivElement>(null);
  const sessionIdRef = useRef(session.sessionId);
  const previousSessionIdRef = useRef(session.sessionId);
  const submittingRef = useRef(false);
  sessionIdRef.current = session.sessionId;
  const chatReady = readiness.data?.chat_ready === true;
  const showLiveAnswer = !answerPersisted && (isRunning || state.answer.trim().length > 0);
  useEffect(() => {
    senderRef.current?.inputElement?.setAttribute('aria-label', '向循证助手提问');
  }, []);
  useEffect(() => {
    if (previousSessionIdRef.current !== session.sessionId) {
      reset();
      setDraft('');
      setValidationMessage(null);
      setAnswerPersisted(false);
      setCitationDrawerOpen(false);
      setSelectedCitations([]);
      submittingRef.current = false;
      previousSessionIdRef.current = session.sessionId;
    }
  }, [reset, session.sessionId]);
  useEffect(() => {
    messageEndRef.current?.scrollIntoView({
      behavior: state.phase === 'streaming' ? 'auto' : 'smooth',
      block: 'end',
    });
  }, [session.messages.length, state.answer, state.phase]);
  function openCitations(citations: readonly Citation[]) {
    setSelectedCitations(citations);
    setCitationDrawerOpen(true);
  }
  function persistAssistant(result: typeof state | null, requestSessionId: string) {
    if (
      !result ||
      result.phase !== 'done' ||
      !result.answer.trim() ||
      sessionIdRef.current !== requestSessionId
    ) {
      return;
    }
    const message: StoredChatMessage = {
      id: result.requestId ? `assistant-${result.requestId}` : crypto.randomUUID(),
      role: 'assistant',
      content: result.answer,
      createdAt: Date.now(),
      citations: result.citations,
    };
    appendMessage(message);
    setAnswerPersisted(true);
  }
  async function handleSubmit(rawValue: string) {
    if (submittingRef.current || isRunning) return;
    const message = rawValue.trim();
    if (!message) {
      setValidationMessage('请输入问题后再发送。');
      return;
    }
    if (message.length > MAX_CHAT_MESSAGE_LENGTH) {
      setValidationMessage(`问题不能超过 ${MAX_CHAT_MESSAGE_LENGTH} 个字符。`);
      return;
    }
    if (!chatReady) {
      setValidationMessage('本地问答服务尚未就绪。');
      return;
    }
    submittingRef.current = true;
    setValidationMessage(null);
    setAnswerPersisted(false);
    const requestSessionId = session.sessionId;
    const history = toApiHistory(session.messages);
    appendMessage({
      id: crypto.randomUUID(),
      role: 'user',
      content: message,
      createdAt: Date.now(),
    });
    setDraft('');
    try {
      const result = await send({
        session_id: requestSessionId,
        message,
        history,
        trace_level: 'summary',
      });
      persistAssistant(result, requestSessionId);
    } catch {
      // useChatStream exposes a sanitized public error in state.
    } finally {
      submittingRef.current = false;
    }
  }
  async function handleRetry() {
    if (!canRetry || submittingRef.current || isRunning) return;
    submittingRef.current = true;
    setAnswerPersisted(false);
    setValidationMessage(null);
    const requestSessionId = session.sessionId;
    try {
      const result = await retry();
      persistAssistant(result, requestSessionId);
    } catch {
      // useChatStream exposes a sanitized public error in state.
    } finally {
      submittingRef.current = false;
    }
  }
  function handleClear() {
    reset();
    clear();
    setDraft('');
    setValidationMessage(null);
    setAnswerPersisted(false);
    setCitationDrawerOpen(false);
    setSelectedCitations([]);
    submittingRef.current = false;
  }
  function handleDraftChange(value: string) {
    if (value.length > MAX_CHAT_MESSAGE_LENGTH) {
      setDraft(value.slice(0, MAX_CHAT_MESSAGE_LENGTH));
      setValidationMessage(`问题不能超过 ${MAX_CHAT_MESSAGE_LENGTH} 个字符。`);
      return;
    }
    setDraft(value);
    if (validationMessage) setValidationMessage(null);
  }
  const transcriptIsEmpty = session.messages.length === 0 && !showLiveAnswer;
  const healthText = readiness.isPending
    ? '正在检查本地服务'
    : chatReady
      ? '问答服务已就绪'
      : '问答服务未就绪';
  return (
    <main className="mx-auto max-w-[1440px] px-3 py-4 sm:px-6 sm:py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-teal-100 bg-white px-4 py-3 shadow-sm">
        <Space wrap>
          <Badge
            status={readiness.isPending ? 'processing' : chatReady ? 'success' : 'error'}
            text={healthText}
          />
          {readiness.isFetching && !readiness.isPending && <LoadingOutlined />}
          <Tag
            icon={<SafetyCertificateOutlined />}
            color={readiness.data?.chat_mode === 'openai_compatible' ? 'green' : 'gold'}
          >
            {readiness.data?.chat_mode === 'openai_compatible'
              ? '真实模型 · OpenAI-compatible'
              : '确定性 Demo · 非模型生成'}
          </Tag>
          <Tag color="cyan">当前标签页临时会话 · 30 分钟无操作自动清除</Tag>
        </Space>
        <Space wrap>
          {(readiness.isError || !chatReady) && !readiness.isPending && (
            <Button icon={<ReloadOutlined />} onClick={() => void readiness.refetch()}>
              重新检查
            </Button>
          )}
          <Popconfirm
            title="清空当前会话？"
            description="本标签页中的消息和当前生成状态将被删除。"
            okText="清空"
            cancelText="取消"
            onConfirm={handleClear}
          >
            <Button danger icon={<DeleteOutlined />}>
              清空会话
            </Button>
          </Popconfirm>
        </Space>
      </div>
      {readiness.isError && (
        <Alert
          className="mb-4"
          type="error"
          showIcon
          message="无法连接本地后端"
          description="请确认 API 服务已启动，然后重新检查。"
          role="alert"
        />
      )}
      {!readiness.isPending && !readiness.isError && !chatReady && (
        <Alert
          className="mb-4"
          type="warning"
          showIcon
          message="聊天服务尚未就绪"
          description="后端仍在启动或检索/模型依赖不可用，暂时不能发送问题。"
        />
      )}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section
          className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
          aria-label="问答对话"
        >
          <div className="flex min-h-[32rem] max-h-[68vh] flex-col sm:min-h-[38rem]">
            <div className="flex-1 space-y-4 overflow-y-auto p-3 sm:p-5">
              {transcriptIsEmpty ? (
                <div className="flex min-h-[24rem] flex-col items-center justify-center gap-4 text-center">
                  <Empty description="开始一次基于本地证据的问答" />
                  <div className="flex max-w-2xl flex-wrap justify-center gap-2">
                    {SUGGESTED_QUESTIONS.map((question) => (
                      <Button key={question} onClick={() => setDraft(question)}>
                        {question}
                      </Button>
                    ))}
                  </div>
                </div>
              ) : (
                session.messages.map((message) => (
                  <MessageBubble
                    key={message.id}
                    role={message.role}
                    content={message.content}
                    citations={message.citations}
                    onOpenCitations={openCitations}
                  />
                ))
              )}
              <SafetyNotices events={state.safetyEvents} />
              {showLiveAnswer && (
                <MessageBubble
                  role="assistant"
                  content={state.answer}
                  citations={state.citations}
                  streaming={isRunning}
                  statusLabel={PHASE_LABELS[state.phase]}
                  onOpenCitations={openCitations}
                />
              )}
              {state.publicError && (
                <Alert
                  type="error"
                  showIcon
                  role="alert"
                  message={state.publicError.message}
                  description={
                    <Space direction="vertical" size={4}>
                      {state.publicError.supportId && (
                        <Typography.Text
                          copyable={{ text: state.publicError.supportId }}
                          code
                        >
                          支持编号：{state.publicError.supportId}
                        </Typography.Text>
                      )}
                      {canRetry && (
                        <Button icon={<ReloadOutlined />} onClick={() => void handleRetry()}>
                          重试本次问题
                        </Button>
                      )}
                    </Space>
                  }
                />
              )}
              {state.phase === 'cancelled' && (
                <Alert
                  type="info"
                  showIcon
                  message="已停止生成"
                  description={
                    canRetry ? (
                      <Button icon={<ReloadOutlined />} onClick={() => void handleRetry()}>
                        重新生成
                      </Button>
                    ) : null
                  }
                />
              )}
              <div ref={messageEndRef} />
            </div>
            <div className="border-t border-slate-200 bg-slate-50 p-3 sm:p-4">
              {validationMessage && (
                <Alert
                  className="mb-3"
                  type="warning"
                  showIcon
                  message={validationMessage}
                  role="alert"
                />
              )}
              <div className="mb-2 flex items-center justify-between gap-2">
                <label className="text-sm font-semibold text-slate-700">向循证助手提问</label>
                <span className="text-xs text-slate-500" role="status" aria-live="polite">
                  {PHASE_LABELS[state.phase]}
                </span>
              </div>
              <Sender
                ref={senderRef}
                value={draft}
                onChange={handleDraftChange}
                onSubmit={(value) => void handleSubmit(value)}
                onCancel={cancel}
                loading={isRunning}
                disabled={!chatReady || readiness.isPending}
                placeholder="输入癫痫相关问题；Enter 发送，Shift + Enter 换行"
                submitType="enter"
                autoSize={{ minRows: 2, maxRows: 6 }}
                footer={
                  <div className="flex w-full items-center justify-between gap-3 px-1 text-xs text-slate-500">
                    <span>每次请求最多携带最近 12 条上下文</span>
                    <span
                      className={
                        draft.length >= MAX_CHAT_MESSAGE_LENGTH
                          ? 'font-semibold text-amber-700'
                          : undefined
                      }
                    >
                      {draft.length}/{MAX_CHAT_MESSAGE_LENGTH}
                    </span>
                  </div>
                }
              />
              {isRunning && (
                <Button className="mt-2" icon={<StopOutlined />} onClick={cancel} danger>
                  停止生成
                </Button>
              )}
            </div>
          </div>
        </section>
        <aside className="space-y-4" aria-label="问答详情">
          <Card className="shadow-sm">
            <TraceTimeline entries={state.trace} active={isRunning} />
          </Card>
          <Card title="会话隐私" size="small" className="shadow-sm">
            <div className="space-y-2 text-sm leading-6 text-slate-600">
              <p className="m-0">消息仅保存在当前标签页的 sessionStorage 中。</p>
              <p className="m-0">30 分钟无操作后自动换新会话；关闭标签页即失效。</p>
              <p className="m-0">发送问题时只携带最近 12 条对话，不展示内部思维链。</p>
            </div>
          </Card>
        </aside>
      </div>
      <CitationDrawer
        open={citationDrawerOpen}
        citations={selectedCitations}
        onClose={() => setCitationDrawerOpen(false)}
      />
    </main>
  );
}
