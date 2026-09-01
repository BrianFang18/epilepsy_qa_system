import { ApiError, apiErrorFromResponse, isAbortError } from './apiError';

export type JsonParser<T> = (value: unknown) => T;

export interface RequestJsonOptions extends RequestInit {
  fetcher?: typeof fetch;
}

export async function requestJson<T = undefined>(
  url: string,
  options: RequestJsonOptions = {},
  parser?: JsonParser<T>,
): Promise<T> {
  const { fetcher = fetch, headers, ...init } = options;
  let response: Response;
  try {
    response = await fetcher(url, {
      ...init,
      cache: 'no-store',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...headers,
      },
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ApiError('无法连接本地服务，请稍后重试。', 0, 'NETWORK_ERROR');
  }

  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError('服务返回了无法识别的数据。', 502, 'INVALID_JSON_RESPONSE');
  }

  if (!parser) {
    return payload as T;
  }
  try {
    return parser(payload);
  } catch {
    throw new ApiError('服务返回了不兼容的数据。', 502, 'INVALID_API_RESPONSE');
  }
}

export function jsonBody(value: unknown): Pick<RequestInit, 'body' | 'headers'> {
  return {
    body: JSON.stringify(value),
    headers: { 'Content-Type': 'application/json' },
  };
}

export function isAuthenticationError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

export function shouldRetryAdminRequest(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failureCount < 1;
}
