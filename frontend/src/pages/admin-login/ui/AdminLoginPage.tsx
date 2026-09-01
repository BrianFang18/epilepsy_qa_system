import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Form, Input, Space, Spin, Typography } from 'antd';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import {
  useAdminLogin,
  useAdminSession,
} from '../../../features/admin-auth/model/useAdminAuth';
import { isAuthenticationError } from '../../../shared/api/requestJson';
interface LoginValues {
  username: string;
  password: string;
}
function safeReturnPath(state: unknown): string {
  if (typeof state !== 'object' || state === null || !('from' in state)) {
    return '/admin/documents';
  }
  const from = (state as { from?: unknown }).from;
  return typeof from === 'string' && from.startsWith('/admin/') && from !== '/admin/login'
    ? from
    : '/admin/documents';
}
export default function AdminLoginPage() {
  const [form] = Form.useForm<LoginValues>();
  const location = useLocation();
  const navigate = useNavigate();
  const session = useAdminSession();
  const login = useAdminLogin();
  if (session.isPending) {
    return (
      <div className="grid min-h-screen place-items-center" aria-label="正在验证管理员会话">
        <Spin size="large" />
      </div>
    );
  }
  if (session.data) {
    return <Navigate replace to="/admin/documents" />;
  }
  const submit = async (values: LoginValues) => {
    try {
      await login.login(values);
      form.setFieldValue('password', '');
      navigate(safeReturnPath(location.state), { replace: true });
    } catch {
      form.setFieldValue('password', '');
      form.focusField('password');
    }
  };
  const serviceError =
    session.error && !isAuthenticationError(session.error) ? session.error : null;
  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <Card className="w-full max-w-md shadow-panel">
        <Space className="mb-6 w-full" orientation="vertical" size={4}>
          <SafetyCertificateOutlined className="text-3xl text-teal-700" />
          <Typography.Title className="!mb-0" level={2}>
            管理员登录
          </Typography.Title>
          <Typography.Text type="secondary">
            会话通过 HttpOnly Cookie 保存，不会写入浏览器存储。
          </Typography.Text>
        </Space>
        {serviceError ? (
          <Alert className="mb-4" type="warning" showIcon message={serviceError.message} />
        ) : null}
        {login.error ? (
          <Alert className="mb-4" type="error" showIcon message={login.error.message} />
        ) : null}
        <Form<LoginValues>
          form={form}
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => void submit(values)}
          onValuesChange={login.reset}
        >
          <Form.Item
            label="用户名"
            name="username"
            rules={[{ required: true, min: 3, max: 128, message: '请输入有效用户名' }]}
          >
            <Input autoComplete="username" prefix={<UserOutlined />} size="large" />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, min: 8, max: 256, message: '请输入至少 8 位密码' }]}
          >
            <Input.Password
              autoComplete="current-password"
              prefix={<LockOutlined />}
              size="large"
            />
          </Form.Item>
          <Button
            block
            htmlType="submit"
            loading={login.isPending}
            size="large"
            type="primary"
          >
            登录
          </Button>
        </Form>
        <div className="mt-5 text-center">
          <Link to="/">返回公开问答页面</Link>
        </div>
      </Card>
    </main>
  );
}
