import {
  parseAdminSession,
  type AdminSession,
} from '../../../entities/admin-session/model/contracts';
import { jsonBody, requestJson } from '../../../shared/api/requestJson';
import { API_ENDPOINTS } from '../../../shared/config/endpoints';

export interface AdminCredentials {
  username: string;
  password: string;
}

export function getAdminSession(fetcher: typeof fetch = fetch): Promise<AdminSession> {
  return requestJson(API_ENDPOINTS.adminSession, { fetcher }, parseAdminSession);
}

export function loginAdmin(
  credentials: AdminCredentials,
  fetcher: typeof fetch = fetch,
): Promise<AdminSession> {
  return requestJson(
    API_ENDPOINTS.adminSession,
    {
      method: 'POST',
      fetcher,
      ...jsonBody(credentials),
    },
    parseAdminSession,
  );
}

export function logoutAdmin(fetcher: typeof fetch = fetch): Promise<void> {
  return requestJson(API_ENDPOINTS.adminSession, { method: 'DELETE', fetcher });
}
