import { Empty, Tag, Timeline, Typography } from 'antd';
import type { TraceEntry, TraceStatus } from '../model/contracts';
interface TraceTimelineProps {
  entries: readonly TraceEntry[];
  active?: boolean;
}
const NODE_LABELS: Record<string, string> = {
  input_emergency_guard: '紧急风险筛查',
  normalize_coreference: '问题规范化',
  retrieve: '混合证据检索',
  evidence_sufficiency: '证据充分性检查',
  generation_preparation: '回答上下文准备',
  output_policy: '输出安全策略',
};
const STATUS_LABELS: Record<TraceStatus, string> = {
  completed: '完成',
  skipped: '跳过',
  blocked: '阻断',
};
const STATUS_COLORS: Record<TraceStatus, string> = {
  completed: 'green',
  skipped: 'default',
  blocked: 'red',
};
export function TraceTimeline({ entries, active = false }: TraceTimelineProps) {
  const sorted = [...entries].sort((left, right) => left.sequence - right.sequence);
  return (
    <section aria-labelledby="trace-title" aria-busy={active}>
      <div className="mb-3">
        <Typography.Title id="trace-title" level={4} className="!mb-1 !mt-0">
          处理轨迹
        </Typography.Title>
        <Typography.Text type="secondary" className="text-xs">
          仅展示执行节点、状态、数量与耗时，不包含模型思维链。
        </Typography.Text>
      </div>
      {sorted.length === 0 ? (
        <Empty
          description={active ? '正在等待处理节点…' : '提问后将在此展示公开处理轨迹'}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <Timeline
          items={sorted.map((entry) => ({
            color:
              entry.status === 'blocked'
                ? 'red'
                : entry.status === 'skipped'
                  ? 'gray'
                  : 'green',
            content: (
              <div data-testid={`trace-${entry.node}`}>
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-800">
                    {NODE_LABELS[entry.node] ?? entry.node}
                  </span>
                  <Tag color={STATUS_COLORS[entry.status]}>{STATUS_LABELS[entry.status]}</Tag>
                </div>
                <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                  {entry.count !== null && <span>数量 {entry.count}</span>}
                  <span>耗时 {Math.round(entry.duration_ms)} ms</span>
                  <span>序号 {entry.sequence}</span>
                </div>
              </div>
            ),
          }))}
        />
      )}
    </section>
  );
}
