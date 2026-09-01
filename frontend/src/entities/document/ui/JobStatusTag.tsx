import { Tag } from 'antd';

import type { DocumentStatus, JobStatus } from '../model/contracts';

const STATUS_LABELS: Record<DocumentStatus | JobStatus, string> = {
  uploaded: '已上传',
  queued: '排队中',
  processing: '处理中',
  running: '运行中',
  retry_wait: '等待重试',
  active: '已生效',
  succeeded: '已完成',
  failed: '失败',
  canceled: '已取消',
};

const STATUS_COLORS: Record<DocumentStatus | JobStatus, string> = {
  uploaded: 'default',
  queued: 'processing',
  processing: 'processing',
  running: 'processing',
  retry_wait: 'warning',
  active: 'success',
  succeeded: 'success',
  failed: 'error',
  canceled: 'default',
};

export function JobStatusTag({ status }: { status: DocumentStatus | JobStatus }) {
  return <Tag color={STATUS_COLORS[status]}>{STATUS_LABELS[status]}</Tag>;
}
