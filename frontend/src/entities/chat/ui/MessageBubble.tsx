import { FileSearchOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import { Button, Tag } from 'antd';
import type { Citation } from '../model/contracts';
import { SafeMarkdown } from './LazySafeMarkdown';
interface MessageBubbleProps {
  role: 'user' | 'assistant';
  content: string;
  citations?: readonly Citation[];
  streaming?: boolean;
  statusLabel?: string;
  onOpenCitations?: (citations: readonly Citation[]) => void;
}
export function MessageBubble({
  role,
  content,
  citations = [],
  streaming = false,
  statusLabel,
  onOpenCitations,
}: MessageBubbleProps) {
  const assistant = role === 'assistant';
  return (
    <article
      aria-label={assistant ? '助手消息' : '用户消息'}
      aria-live={streaming ? 'polite' : undefined}
      aria-atomic={streaming ? 'false' : undefined}
      className={`flex gap-3 ${assistant ? 'justify-start' : 'justify-end'}`}
    >
      {assistant && (
        <div
          aria-hidden="true"
          className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-700 text-white"
        >
          <RobotOutlined />
        </div>
      )}
      <div
        className={`max-w-[min(48rem,88%)] rounded-2xl px-4 py-3 shadow-sm ${
          assistant ? 'border border-slate-200 bg-white' : 'bg-teal-700 text-white'
        }`}
      >
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold">
          <span>{assistant ? '循证助手' : '你'}</span>
          {statusLabel && (
            <Tag color={streaming ? 'processing' : 'default'}>{statusLabel}</Tag>
          )}
        </div>
        {assistant ? (
          content ? (
            <SafeMarkdown>{content}</SafeMarkdown>
          ) : (
            <p className="m-0 text-sm text-slate-500">正在连接本地问答服务…</p>
          )
        ) : (
          <p className="m-0 whitespace-pre-wrap break-words leading-7">{content}</p>
        )}
        {assistant && citations.length > 0 && onOpenCitations && (
          <Button
            className="mt-3"
            icon={<FileSearchOutlined />}
            onClick={() => onOpenCitations(citations)}
            size="small"
          >
            查看 {citations.length} 条证据
          </Button>
        )}
      </div>
      {!assistant && (
        <div
          aria-hidden="true"
          className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky-700 text-white"
        >
          <UserOutlined />
        </div>
      )}
    </article>
  );
}
