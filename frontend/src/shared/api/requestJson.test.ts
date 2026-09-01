import { ApiError } from './apiError';
import { isAuthenticationError, requestJson, shouldRetryAdminRequest } from './requestJson';
describe('requestJson', () => {
  it('uses same-origin credentials and validates JSON with the supplied parser', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify({ value: 7 }), { status: 200 }));
    const result = await requestJson(
      '/api/example',
      { fetcher },
      (value) => (value as { value: number }).value,
    );
    expect(result).toBe(7);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
  });
  it('sanitizes HTTP, malformed payload, and network failures', async () => {
    const unauthorized = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'database and password internals' }), {
        status: 401,
      }),
    );
    const authError = await requestJson('/api/private', { fetcher: unauthorized }).catch(
      (error: unknown) => error,
    );
    expect(authError).toBeInstanceOf(ApiError);
    expect(authError).toMatchObject({ status: 401, code: 'HTTP_401' });
    expect((authError as Error).message).not.toContain('database');
    expect(isAuthenticationError(authError)).toBe(true);
    await expect(
      requestJson(
        '/api/malformed',
        {
          fetcher: vi
            .fn<typeof fetch>()
            .mockResolvedValue(
              new Response(JSON.stringify({ wrong: true }), { status: 200 }),
            ),
        },
        () => {
          throw new Error('private parser detail');
        },
      ),
    ).rejects.toMatchObject({ code: 'INVALID_API_RESPONSE' });
    await expect(
      requestJson('/api/offline', {
        fetcher: vi
          .fn<typeof fetch>()
          .mockRejectedValue(new TypeError('private proxy detail')),
      }),
    ).rejects.toMatchObject({ code: 'NETWORK_ERROR', status: 0 });
  });
  it('supports no-content responses and does not retry authentication failures', async () => {
    const result = await requestJson('/api/logout', {
      fetcher: vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 204 })),
    });
    expect(result).toBeUndefined();
    expect(shouldRetryAdminRequest(0, new ApiError('auth', 401, 'HTTP_401'))).toBe(false);
    expect(shouldRetryAdminRequest(0, new Error('network'))).toBe(true);
    expect(shouldRetryAdminRequest(1, new Error('network'))).toBe(false);
  });
});
