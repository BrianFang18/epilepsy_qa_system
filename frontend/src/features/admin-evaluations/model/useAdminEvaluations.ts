import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { isTerminalJob } from '../../../entities/document/model/contracts';
import { shouldRetryAdminRequest } from '../../../shared/api/requestJson';
import {
  createEvaluation,
  getEvaluationSummary,
  listEvaluations,
  type CreateEvaluationInput,
} from '../api/adminEvaluations';
export const evaluationKeys = {
  all: ['admin', 'evaluations'] as const,
  list: (limit: number, offset: number) =>
    ['admin', 'evaluations', 'list', limit, offset] as const,
  summary: ['admin', 'evaluations', 'summary'] as const,
};
export function useAdminEvaluations(limit = 25, offset = 0) {
  return useQuery({
    queryKey: evaluationKeys.list(limit, offset),
    queryFn: () => listEvaluations(limit, offset),
    retry: shouldRetryAdminRequest,
    refetchInterval: (query) => {
      const jobs = query.state.data?.items;
      return jobs?.some((job) => !isTerminalJob(job.status)) ? 3_000 : false;
    },
  });
}
export function useEvaluationSummary() {
  return useQuery({
    queryKey: evaluationKeys.summary,
    queryFn: () => getEvaluationSummary(),
    retry: shouldRetryAdminRequest,
    staleTime: 5_000,
    refetchInterval: 5_000,
  });
}
export function useCreateEvaluation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateEvaluationInput) => createEvaluation(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: evaluationKeys.all });
    },
  });
}
