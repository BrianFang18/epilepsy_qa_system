import { ExperimentOutlined, PlayCircleOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Progress,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  type TableProps,
} from 'antd';
import { useState } from 'react';

import { JobStatusTag } from '../../../entities/document/ui/JobStatusTag';
import {
  EVALUATION_SUITES,
  type EvaluationJob,
  type EvaluationSuite,
} from '../../../entities/evaluation/model/contracts';
import { useRedirectOnUnauthorized } from '../../../features/admin-auth/model/useAdminAuth';
import {
  useAdminEvaluations,
  useCreateEvaluation,
  useEvaluationSummary,
} from '../../../features/admin-evaluations/model/useAdminEvaluations';
import { formatDateTime, formatMetric } from '../../../shared/lib/format';

const EVALUATION_RUNNER_CONFIGURED = false;
const SUITE_LABELS: Record<EvaluationSuite, string> = {
  smoke: '冒烟检查',
  retrieval: '检索评估',
  generation: '生成评估',
  safety: '安全评估',
  full: '完整评估',
};

interface EvaluationValues {
  name: string;
  suite: EvaluationSuite;
}

export default function AdminEvaluationsPage() {
  const [form] = Form.useForm<EvaluationValues>();
  const [page, setPage] = useState(1);
  const evaluations = useAdminEvaluations(25, (page - 1) * 25);
  const summary = useEvaluationSummary();
  const create = useCreateEvaluation();
  useRedirectOnUnauthorized(evaluations.error ?? summary.error ?? create.error);

  const submit = async (values: EvaluationValues) => {
    if (!EVALUATION_RUNNER_CONFIGURED) return;
    try {
      await create.mutateAsync({ name: values.name.trim(), suite: values.suite });
      form.resetFields();
    } catch {
      // The sanitized mutation error is rendered below.
    }
  };

  const columns: TableProps<EvaluationJob>['columns'] = [
    {
      title: '评估任务',
      key: 'name',
      render: (_, item) => (
        <Space orientation="vertical" size={0}>
          <Typography.Text strong>{item.name}</Typography.Text>
          <Typography.Text type="secondary">{SUITE_LABELS[item.suite]}</Typography.Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status: EvaluationJob['status']) => <JobStatusTag status={status} />,
    },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 150,
      render: (progress: number, item) => (
        <Progress
          percent={progress}
          size="small"
          status={item.status === 'failed' ? 'exception' : undefined}
        />
      ),
    },
    {
      title: '聚合指标',
      dataIndex: 'aggregate_metrics',
      render: (metrics: Record<string, number>) =>
        Object.keys(metrics).length ? (
          <Space size={[4, 4]} wrap>
            {Object.entries(metrics).map(([name, value]) => (
              <Tag key={name}>{`${name}: ${formatMetric(value)}`}</Tag>
            ))}
          </Space>
        ) : (
          '—'
        ),
    },
    {
      title: '执行结果',
      key: 'error',
      width: 220,
      render: (_, item) =>
        item.error_code || item.error_message ? (
          <Typography.Text type="danger">
            {item.error_code ?? item.error_message}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
  ];

  const metricEntries = Object.entries(summary.data?.latest_metrics ?? {});

  return (
    <Space className="w-full" orientation="vertical" size="large">
      <div>
        <Typography.Title className="!mb-1" level={2}>
          评估看板
        </Typography.Title>
        <Typography.Text type="secondary">
          用受控测试集衡量检索、生成与安全表现；它不是文档摄取，也不是聊天记录统计。
        </Typography.Text>
      </div>

      <Alert
        type="warning"
        showIcon
        message="当前没有配置真实评估执行器"
        description="创建入口已禁用，API 也会拒绝新任务，避免生成永远排队或看似真实的伪指标。下方仅保留历史任务和聚合结果；仓库中的 public evaluation dry-run 是独立的合成结构校验，不等于模型质量评估。"
      />

      <Alert
        type="info"
        showIcon
        message="隐私边界"
        description="未来接入评估器后，敏感评估明细也只可写入私有对象存储；PostgreSQL 与本页面只保留汇总数值。"
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <Statistic title="历史评估任务" value={summary.data?.total ?? 0} />
        </Card>
        {Object.entries(summary.data?.status_counts ?? {})
          .slice(0, 3)
          .map(([status, count]) => (
            <Card key={status}>
              <Statistic title={`状态 · ${status}`} value={count} />
            </Card>
          ))}
      </div>

      <Card title="最新完成指标" extra={<ExperimentOutlined className="text-teal-700" />}>
        {metricEntries.length ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {metricEntries.map(([name, value]) => (
              <Statistic key={name} title={name} value={formatMetric(value)} />
            ))}
          </div>
        ) : (
          <Empty
            description="尚无真实评估器产生的聚合指标"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        )}
      </Card>

      <Card title="创建评估任务（未配置）">
        <Form<EvaluationValues>
          disabled={!EVALUATION_RUNNER_CONFIGURED}
          form={form}
          initialValues={{ suite: 'smoke' }}
          layout="vertical"
          onFinish={(values) => void submit(values)}
        >
          <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(12rem,1fr)_auto] md:items-end">
            <Form.Item
              label="任务名称"
              name="name"
              rules={[
                { required: true, whitespace: true, message: '请输入任务名称' },
                { max: 255 },
              ]}
            >
              <Input placeholder="接入真实 evaluator 后才可创建" />
            </Form.Item>
            <Form.Item label="评估套件" name="suite" rules={[{ required: true }]}>
              <Select
                options={EVALUATION_SUITES.map((suite) => ({
                  value: suite,
                  label: SUITE_LABELS[suite],
                }))}
              />
            </Form.Item>
            <Form.Item label=" ">
              <Button
                disabled
                htmlType="submit"
                icon={<PlayCircleOutlined />}
                loading={create.isPending}
                type="primary"
              >
                未配置执行器
              </Button>
            </Form.Item>
          </div>
        </Form>
        {create.error ? (
          <Alert className="mt-2" type="error" showIcon message={create.error.message} />
        ) : null}
      </Card>

      <Card title="历史评估记录">
        {evaluations.error ? (
          <Alert className="mb-4" type="error" showIcon message={evaluations.error.message} />
        ) : null}
        <Table<EvaluationJob>
          columns={columns}
          dataSource={evaluations.data?.items ?? []}
          loading={evaluations.isPending}
          pagination={{
            current: page,
            pageSize: 25,
            total: evaluations.data?.total ?? 0,
            showSizeChanger: false,
            onChange: setPage,
          }}
          rowKey="id"
          scroll={{ x: 1050 }}
        />
      </Card>
    </Space>
  );
}
