import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { App as AntApp } from 'antd';
import { App } from '../App';
function renderRouter(path: string, fetcher: typeof fetch) {
  window.history.pushState({}, '', path);
  vi.stubGlobal('fetch', fetcher);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AntApp>
        <App />
      </AntApp>
    </QueryClientProvider>,
  );
}
describe('admin routes', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, '', '/');
  });
  it('redirects an unauthenticated deep link to the login page', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: 'Authentication required' }), {
          status: 401,
        }),
    );
    renderRouter('/admin/documents', fetcher);
    expect(await screen.findByRole('heading', { name: '管理员登录' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/admin/login');
  });
  it('renders the protected document page for a valid cookie session', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = String(input);
      if (url === '/api/v1/admin/session') {
        return new Response(
          JSON.stringify({
            user: { id: 'admin-1', username: 'admin' },
            expires_at: '2026-08-26T12:00:00Z',
          }),
          { status: 200 },
        );
      }
      if (url.startsWith('/api/v1/admin/documents')) {
        return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
      }
      return new Response(null, { status: 404 });
    });
    renderRouter('/admin/documents', fetcher);
    expect(await screen.findByRole('heading', { name: '文档摄取' })).toBeInTheDocument();
    expect(screen.getByText('admin')).toBeInTheDocument();
  });
});
