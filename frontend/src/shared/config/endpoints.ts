export const API_ENDPOINTS = {
  chatStream: '/api/v1/chat/stream',
  readiness: '/health/ready',
  adminSession: '/api/v1/admin/session',
  adminDocuments: '/api/v1/admin/documents',
  adminDocument: (documentId: string) =>
    `/api/v1/admin/documents/${encodeURIComponent(documentId)}`,
  adminIngestionJob: (jobId: string) =>
    `/api/v1/admin/ingestion-jobs/${encodeURIComponent(jobId)}`,
  adminIngestionRetry: (jobId: string) =>
    `/api/v1/admin/ingestion-jobs/${encodeURIComponent(jobId)}/retry`,
  adminIngestionCancel: (jobId: string) =>
    `/api/v1/admin/ingestion-jobs/${encodeURIComponent(jobId)}/cancel`,
  adminEvaluations: '/api/v1/admin/evaluations',
  adminEvaluationSummary: '/api/v1/admin/evaluations/summary',
  adminEvaluation: (jobId: string) =>
    `/api/v1/admin/evaluations/${encodeURIComponent(jobId)}`,
} as const;
