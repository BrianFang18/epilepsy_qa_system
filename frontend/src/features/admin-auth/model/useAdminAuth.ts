import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import type { AdminSession } from '../../../entities/admin-session/model/contracts';
import { ApiError } from '../../../shared/api/apiError';
import {
  isAuthenticationError,
  shouldRetryAdminRequest,
} from '../../../shared/api/requestJson';
import {
  getAdminSession,
  loginAdmin,
  logoutAdmin,
  type AdminCredentials,
} from '../api/adminAuth';

export const adminSessionKey = ['admin', 'session'] as const;

export function useAdminSession() {
  return useQuery({
    queryKey: adminSessionKey,
    queryFn: () => getAdminSession(),
    retry: shouldRetryAdminRequest,
    staleTime: 30_000,
  });
}

export function useAdminLogin() {
  const queryClient = useQueryClient();
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const login = useCallback(
    async (credentials: AdminCredentials): Promise<AdminSession> => {
      setIsPending(true);
      setError(null);
      try {
        const session = await loginAdmin(credentials);
        queryClient.setQueryData(adminSessionKey, session);
        return session;
      } catch (loginError) {
        const publicError =
          loginError instanceof ApiError
            ? loginError
            : new Error('无法连接管理服务，请检查本地后端。');
        setError(publicError);
        throw publicError;
      } finally {
        setIsPending(false);
      }
    },
    [queryClient],
  );

  return { login, isPending, error, reset: () => setError(null) };
}

export function useAdminLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => logoutAdmin(),
    onSettled: async () => {
      await queryClient.cancelQueries({ queryKey: ['admin'] });
      queryClient.removeQueries({ queryKey: ['admin'] });
    },
  });
}

export function useRedirectOnUnauthorized(error: Error | null) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!isAuthenticationError(error)) {
      return;
    }
    void queryClient.cancelQueries({ queryKey: ['admin'] });
    queryClient.removeQueries({ queryKey: ['admin'] });
    navigate('/admin/login', {
      replace: true,
      state: { from: `${location.pathname}${location.search}` },
    });
  }, [error, location.pathname, location.search, navigate, queryClient]);
}
