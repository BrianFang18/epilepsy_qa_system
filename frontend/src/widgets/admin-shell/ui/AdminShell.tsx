import {
  DatabaseOutlined,
  ExperimentOutlined,
  LogoutOutlined,
  MessageOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { Button, Layout, Menu, Space, Typography } from 'antd';
import { useMemo } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  useAdminLogout,
  useAdminSession,
} from '../../../features/admin-auth/model/useAdminAuth';
const { Header, Content, Footer } = Layout;
export default function AdminShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const session = useAdminSession();
  const logout = useAdminLogout();
  const selectedKey = location.pathname.startsWith('/admin/evaluations')
    ? '/admin/evaluations'
    : '/admin/documents';
  const menuItems = useMemo(
    () => [
      { key: '/admin/documents', icon: <DatabaseOutlined />, label: '文档摄取' },
      { key: '/admin/evaluations', icon: <ExperimentOutlined />, label: '评估看板' },
    ],
    [],
  );
  const handleLogout = async () => {
    try {
      await logout.mutateAsync();
    } catch {
      // Local cache is cleared in onSettled even if the server is unavailable.
    }
    navigate('/admin/login', { replace: true });
  };
  return (
    <Layout className="min-h-screen !bg-transparent">
      <Header className="!flex !h-auto min-h-16 flex-wrap items-center gap-3 !bg-white/95 !px-4 py-2 shadow-sm backdrop-blur md:!px-8">
        <Link
          className="flex min-w-fit items-center gap-2 text-teal-800"
          to="/admin/documents"
        >
          <SafetyCertificateOutlined className="text-xl" />
          <Typography.Text strong>癫痫 RAG 管理台</Typography.Text>
        </Link>
        <Menu
          className="min-w-56 flex-1 border-0"
          mode="horizontal"
          items={menuItems}
          selectedKeys={[selectedKey]}
          onClick={({ key }) => navigate(key)}
        />
        <Space wrap>
          <Typography.Text type="secondary">
            {session.data?.user.username ?? '管理员'}
          </Typography.Text>
          <Button icon={<MessageOutlined />} onClick={() => navigate('/')}>
            返回问答
          </Button>
          <Button
            danger
            icon={<LogoutOutlined />}
            loading={logout.isPending}
            onClick={() => void handleLogout()}
          >
            退出
          </Button>
        </Space>
      </Header>
      <Content className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">
        <Outlet />
      </Content>
      <Footer className="!bg-transparent text-center !text-slate-500">
        本地 Demo 管理面 · 不展示私有评估答案或模型思维链
      </Footer>
    </Layout>
  );
}
