import { apiErrorFromResponse } from '../../../shared/api/apiError';
import { API_ENDPOINTS } from '../../../shared/config/endpoints';

export interface BackendReadiness {
  status: 'ready' | 'degraded';
  legacy_ready: boolean;
  chat_ready: boolean;
}

export async function getBackendReadiness(): Promise<BackendReadiness> {
  const response = await fetch(API_ENDPOINTS.readiness, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });
  if (!response.ok) throw await apiErrorFromResponse(response);
  const value = (await response.json()) as Partial<BackendReadiness>;
  if (
    (value.status !== 'ready' && value.status !== 'degraded') ||
    typeof value.legacy_ready !== 'boolean' ||
    typeof value.chat_ready !== 'boolean'
  ) {
    throw new Error('Readiness response is malformed');
  }
  return value as BackendReadiness;
}
