import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import {
  isTerminalJob,
  type AdminDocument,
  type IngestionJob,
} from '../../../entities/document/model/contracts';
import { shouldRetryAdminRequest } from '../../../shared/api/requestJson';
import {
  cancelIngestionJob,
  getIngestionJob,
  listDocuments,
  retryIngestionJob,
  uploadDocument,
  type UploadDocumentInput,
} from '../api/adminDocuments';
export const documentKeys = {
  all: ['admin', 'documents'] as const,
  list: (limit: number, offset: number) =>
    ['admin', 'documents', 'list', limit, offset] as const,
  job: (jobId: string) => ['admin', 'ingestion-job', jobId] as const,
};
export function selectFirstNonTerminalIngestionJob(
  documents: readonly AdminDocument[] | undefined,
): IngestionJob | null {
  for (const document of documents ?? []) {
    const latestJob = document.latest_ingestion_job;
    if (latestJob && !isTerminalJob(latestJob.status)) {
      return latestJob;
    }
  }
  return null;
}
export function useAdminDocuments(limit = 25, offset = 0) {
  return useQuery({
    queryKey: documentKeys.list(limit, offset),
    queryFn: () => listDocuments(limit, offset),
    retry: shouldRetryAdminRequest,
    staleTime: 5_000,
  });
}
export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: UploadDocumentInput) => uploadDocument(input),
    onSuccess: (result) => {
      queryClient.setQueryData(
        documentKeys.job(result.ingestion_job.id),
        result.ingestion_job,
      );
      void queryClient.invalidateQueries({ queryKey: documentKeys.all });
    },
  });
}
export function useIngestionJob(jobId: string | null) {
  return useQuery({
    queryKey: documentKeys.job(jobId ?? 'none'),
    queryFn: () => getIngestionJob(jobId as string),
    enabled: Boolean(jobId),
    retry: shouldRetryAdminRequest,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isTerminalJob(status) ? false : 1_500;
    },
  });
}
export function useIngestionJobWithRecovery(
  documents: readonly AdminDocument[] | undefined,
  activeJobId: string | null,
  onRecover: (jobId: string) => void,
) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (activeJobId) {
      return;
    }
    const recoveredJob = selectFirstNonTerminalIngestionJob(documents);
    if (!recoveredJob) {
      return;
    }
    const queryKey = documentKeys.job(recoveredJob.id);
    if (queryClient.getQueryData(queryKey) === undefined) {
      queryClient.setQueryData(queryKey, recoveredJob);
    }
    onRecover(recoveredJob.id);
  }, [activeJobId, documents, onRecover, queryClient]);
  return useIngestionJob(activeJobId);
}
export function useRetryIngestionJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => retryIngestionJob(jobId),
    onSuccess: (job) => {
      queryClient.setQueryData(documentKeys.job(job.id), job);
    },
  });
}
export function useCancelIngestionJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelIngestionJob(jobId),
    onSuccess: (job) => {
      queryClient.setQueryData(documentKeys.job(job.id), job);
    },
  });
}
