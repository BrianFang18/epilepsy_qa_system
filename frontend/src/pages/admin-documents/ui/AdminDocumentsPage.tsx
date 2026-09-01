import {
  CloudUploadOutlined,
  InboxOutlined,
  ReloadOutlined,
  StopOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Progress,
  Select,
  Space,
  Table,
  Typography,
  Upload,
  type TableProps,
  type UploadFile,
} from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  isTerminalJob,
  type AdminDocument,
  type IngestionJob,
  type JobStage,
} from '../../../entities/document/model/contracts';
import { JobStatusTag } from '../../../entities/document/ui/JobStatusTag';
import {
  documentKeys,
  useAdminDocuments,
  useCancelIngestionJob,
  useIngestionJobWithRecovery,
  useRetryIngestionJob,
  useUploadDocument,
} from '../../../features/admin-documents/model/useAdminDocuments';
import { useRedirectOnUnauthorized } from '../../../features/admin-auth/model/useAdminAuth';
import { formatBytes, formatDateTime } from '../../../shared/lib/format';
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const STAGE_LABELS: Record<JobStage, string> = {
  fetch: '获取原件',
  parse: '解析内容',
  chunk: '父子分块',
  embed: '生成向量',
  index: '写入索引',
  finalize: '完成切换',
};
interface UploadValues {
  title?: string;
  docType: 'literature' | 'clinical';
}
export default function AdminDocumentsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<UploadValues>();
  const [page, setPage] = useState(1);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const notifiedJob = useRef<string | null>(null);
  const documents = useAdminDocuments(25, (page - 1) * 25);
  const upload = useUploadDocument();
  const job = useIngestionJobWithRecovery(documents.data?.items, activeJobId, setActiveJobId);
  const retry = useRetryIngestionJob();
  const cancel = useCancelIngestionJob();
  useRedirectOnUnauthorized(documents.error ?? job.error ?? upload.error);
  useEffect(() => {
    if (!job.data || !isTerminalJob(job.data.status) || notifiedJob.current === job.data.id) {
      return;
    }
    notifiedJob.current = job.data.id;
    void queryClient.invalidateQueries({ queryKey: documentKeys.all });
    if (job.data.status === 'succeeded') {
      void message.success('文档已完成索引并生效。');
    } else if (job.data.status === 'failed') {
      void message.error('文档处理失败，可检查状态后重试。');
    }
  }, [job.data, message, queryClient]);
  const submitUpload = async (values: UploadValues) => {
    if (!selectedFile) {
      void message.warning('请先选择 PDF、TXT 或 Markdown 文件。');
      return;
    }
    try {
      const result = await upload.mutateAsync({
        file: selectedFile,
        title: values.title,
        docType: values.docType,
      });
      notifiedJob.current = null;
      setActiveJobId(result.ingestion_job.id);
      setSelectedFile(null);
      setFileList([]);
      form.resetFields();
      void queryClient.invalidateQueries({ queryKey: documentKeys.all });
      void message.success(
        result.deduplicated ? '已复用相同内容的摄取任务。' : '上传成功，已进入后台队列。',
      );
    } catch {
      // The mutation exposes a sanitized ApiError below.
    }
  };
  const beforeUpload = (file: File & { uid: string }) => {
    const extension = file.name.toLowerCase().match(/\.[^.]+$/)?.[0];
    if (!extension || !['.pdf', '.txt', '.md'].includes(extension)) {
      void message.error('仅支持 PDF、TXT 和 Markdown 文件。');
      return Upload.LIST_IGNORE;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      void message.error('文件不能超过 25 MB。');
      return Upload.LIST_IGNORE;
    }
    setSelectedFile(file);
    return false;
  };
  const showIngestionJob = (latestJob: IngestionJob) => {
    queryClient.setQueryData(documentKeys.job(latestJob.id), latestJob);
    notifiedJob.current = isTerminalJob(latestJob.status) ? latestJob.id : null;
    setActiveJobId(latestJob.id);
  };
  const columns: TableProps<AdminDocument>['columns'] = [
    {
      title: '文档',
      key: 'document',
      render: (_, item) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text strong>{item.title}</Typography.Text>
          <Typography.Text type="secondary">{item.filename}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'doc_type',
      width: 100,
      render: (value: AdminDocument['doc_type']) =>
        value === 'clinical' ? '临床资料' : '文献资料',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: AdminDocument['status']) => <JobStatusTag status={value} />,
    },
    {
      title: '最新任务',
      key: 'latest_ingestion_job',
      width: 170,
      render: (_, item) =>
        item.latest_ingestion_job ? (
          <Space size="small">
            <JobStatusTag status={item.latest_ingestion_job.status} />
            <Button
              size="small"
              type="link"
              onClick={() => showIngestionJob(item.latest_ingestion_job as IngestionJob)}
            >
              查看
            </Button>
          </Space>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
    {
      title: '大小',
      dataIndex: 'size_bytes',
      width: 100,
      render: (value: number) => formatBytes(value),
    },
    {
      title: '内容指纹',
      dataIndex: 'content_sha256',
      width: 150,
      render: (value: string) => (
        <Typography.Text copyable={{ text: value }} code>
          {value.slice(0, 12)}…
        </Typography.Text>
      ),
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
  ];
  return (
    <Space className="w-full" orientation="vertical" size="large">
      <div>
        <Typography.Title className="!mb-1" level={2}>
          文档摄取
        </Typography.Title>
        <Typography.Text type="secondary">
          原件进入 MinIO，状态与任务保存在 PostgreSQL，解析和索引由独立 Worker 完成。
        </Typography.Text>
      </div>
      <Card title="上传完整资料" extra={<CloudUploadOutlined className="text-teal-700" />}>
        <Form<UploadValues>
          form={form}
          initialValues={{ docType: 'literature' }}
          layout="vertical"
          onFinish={(values) => void submitUpload(values)}
        >
          <div className="grid gap-4 md:grid-cols-2">
            <Form.Item label="显示标题（可选）" name="title" rules={[{ max: 255 }]}>
              <Input placeholder="默认使用文件名" />
            </Form.Item>
            <Form.Item label="资料类型" name="docType" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: 'literature', label: '文献资料' },
                  { value: 'clinical', label: '临床资料' },
                ]}
              />
            </Form.Item>
          </div>
          <Upload.Dragger
            accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
            beforeUpload={beforeUpload}
            fileList={fileList}
            maxCount={1}
            multiple={false}
            onChange={({ fileList: next }) => setFileList(next.slice(-1))}
            onRemove={() => {
              setSelectedFile(null);
              setFileList([]);
              return true;
            }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">拖放文件到这里，或点击选择</p>
            <p className="ant-upload-hint">支持 PDF、TXT、Markdown，单文件最多 25 MB</p>
          </Upload.Dragger>
          {upload.error ? (
            <Alert className="mt-4" type="error" showIcon message={upload.error.message} />
          ) : null}
          <Button
            className="mt-4"
            htmlType="submit"
            icon={<CloudUploadOutlined />}
            loading={upload.isPending}
            type="primary"
          >
            上传并排队
          </Button>
        </Form>
      </Card>
      {activeJobId ? (
        <Card title="后台处理进度">
          {job.data ? (
            <Space className="w-full" orientation="vertical" size="middle">
              <Space wrap>
                <JobStatusTag status={job.data.status} />
                <Typography.Text>{STAGE_LABELS[job.data.stage]}</Typography.Text>
                <Typography.Text type="secondary">
                  尝试 {job.data.attempts}/{job.data.max_attempts}
                </Typography.Text>
              </Space>
              <Progress
                percent={job.data.progress}
                status={job.data.status === 'failed' ? 'exception' : undefined}
              />
              <Descriptions column={{ xs: 1, sm: 2, md: 3 }} size="small">
                <Descriptions.Item label="父块">
                  {job.data.inserted_parents}
                </Descriptions.Item>
                <Descriptions.Item label="子块">
                  {job.data.inserted_children}
                </Descriptions.Item>
                <Descriptions.Item label="更新时间">
                  {formatDateTime(job.data.updated_at)}
                </Descriptions.Item>
              </Descriptions>
              {job.data.error_message ? (
                <Alert type="error" showIcon message={job.data.error_message} />
              ) : null}
              <Space>
                {(job.data.status === 'failed' || job.data.status === 'canceled') && (
                  <Button
                    icon={<ReloadOutlined />}
                    loading={retry.isPending}
                    onClick={() => {
                      notifiedJob.current = null;
                      retry.mutate(job.data.id);
                    }}
                  >
                    重试
                  </Button>
                )}
                {!isTerminalJob(job.data.status) ? (
                  <Button
                    danger
                    icon={<StopOutlined />}
                    loading={cancel.isPending}
                    onClick={() => cancel.mutate(job.data.id)}
                  >
                    取消
                  </Button>
                ) : null}
              </Space>
            </Space>
          ) : job.error ? (
            <Alert type="error" showIcon message={job.error.message} />
          ) : (
            <Progress percent={5} status="active" />
          )}
        </Card>
      ) : null}
      <Card title="文档清单">
        {documents.error ? (
          <Alert className="mb-4" type="error" showIcon message={documents.error.message} />
        ) : null}
        <Table<AdminDocument>
          columns={columns}
          dataSource={documents.data?.items ?? []}
          loading={documents.isPending}
          pagination={{
            current: page,
            pageSize: 25,
            total: documents.data?.total ?? 0,
            showSizeChanger: false,
            onChange: setPage,
          }}
          rowKey="id"
          scroll={{ x: 900 }}
        />
      </Card>
    </Space>
  );
}
