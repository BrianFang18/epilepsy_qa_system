import { getAdminSession, loginAdmin, logoutAdmin } from './adminAuth';

const SESSION = {
  user: { id: '4a1464f2-2670-4bb7-bf22-46b55fdab0f9', username: 'admin' },
  expires_at: '2026-08-26T12:00:00Z',
};

describe('admin authentication API', () => {
  it('posts credentials only in the login body and parses the safe session', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(SESSION), { status: 200 }));
    const session = await loginAdmin(
      { username: 'admin', password: 'test-password-123' },
      fetcher,
    );
    expect(session).toEqual(SESSION);
    const [url, init] = fetcher.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/admin/session');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({
      username: 'admin',
      password: 'test-password-123',
    });
  });

  it('bootstraps and clears a cookie-backed session', async () => {
    const sessionFetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(SESSION), { status: 200 }));
    await expect(getAdminSession(sessionFetcher)).resolves.toEqual(SESSION);

    const logoutFetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 204 }));
    await expect(logoutAdmin(logoutFetcher)).resolves.toBeUndefined();
    expect(logoutFetcher.mock.calls[0]?.[1]?.method).toBe('DELETE');
  });
});
