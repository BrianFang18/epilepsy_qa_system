import { asRecord, asString } from '../../../shared/api/contract';

export interface AdminUser {
  id: string;
  username: string;
}

export interface AdminSession {
  user: AdminUser;
  expires_at: string;
}

export function parseAdminSession(value: unknown): AdminSession {
  const root = asRecord(value);
  const user = asRecord(root.user);
  return {
    user: {
      id: asString(user.id, 'user.id'),
      username: asString(user.username, 'user.username'),
    },
    expires_at: asString(root.expires_at, 'expires_at'),
  };
}
