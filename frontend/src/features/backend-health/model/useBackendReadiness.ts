import { useQuery } from '@tanstack/react-query';

import { getBackendReadiness } from '../api/getReadiness';

export function useBackendReadiness() {
  return useQuery({
    queryKey: ['backend-readiness'],
    queryFn: getBackendReadiness,
    retry: 1,
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}
