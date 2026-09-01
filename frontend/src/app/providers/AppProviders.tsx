import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useState, type PropsWithChildren } from 'react';
export function AppProviders({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false },
          mutations: { retry: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          token: {
            colorPrimary: '#0f766e',
            colorInfo: '#0369a1',
            colorSuccess: '#15803d',
            colorWarning: '#b45309',
            colorError: '#b91c1c',
            borderRadius: 12,
            fontFamily: 'Inter, "Noto Sans SC", "Microsoft YaHei", system-ui, sans-serif',
          },
        }}
      >
        <AntApp>{children}</AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  );
}
