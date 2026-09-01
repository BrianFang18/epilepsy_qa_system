import { Button, Result, Spin } from 'antd';
import { lazy, Suspense } from 'react';
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';

import { useAdminSession } from '../../features/admin-auth/model/useAdminAuth';
import { ChatPage } from '../../pages/chat/ui/ChatPage';
import { isAuthenticationError } from '../../shared/api/requestJson';

const AdminLoginPage = lazy(() => import('../../pages/admin-login/ui/AdminLoginPage'));
const AdminDocumentsPage = lazy(
  () => import('../../pages/admin-documents/ui/AdminDocumentsPage'),
);
const AdminEvaluationsPage = lazy(
  () => import('../../pages/admin-evaluations/ui/AdminEvaluationsPage'),
);
const AdminShell = lazy(() => import('../../widgets/admin-shell/ui/AdminShell'));

function RouteFallback() {
  return (
    <div className="grid min-h-screen place-items-center" aria-label="正在加载页面">
      <Spin size="large" />
    </div>
  );
}

function RequireAdmin() {
  const session = useAdminSession();
  const location = useLocation();
  if (session.isPending) {
    return <RouteFallback />;
  }
  if (session.error && isAuthenticationError(session.error)) {
    return (
      <Navigate
        replace
        to="/admin/login"
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }
  if (session.error) {
    return (
      <Result
        status="warning"
        title="管理服务暂不可用"
        subTitle={session.error.message}
        extra={<Button onClick={() => void session.refetch()}>重新检查</Button>}
      />
    );
  }
  return <Outlet />;
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/admin/login" element={<AdminLoginPage />} />
          <Route element={<RequireAdmin />}>
            <Route path="/admin" element={<Navigate replace to="/admin/documents" />} />
            <Route element={<AdminShell />}>
              <Route path="/admin/documents" element={<AdminDocumentsPage />} />
              <Route path="/admin/evaluations" element={<AdminEvaluationsPage />} />
            </Route>
          </Route>
          <Route
            path="*"
            element={
              <Result
                status="404"
                title="页面不存在"
                extra={<Button href="/">返回问答首页</Button>}
              />
            }
          />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
