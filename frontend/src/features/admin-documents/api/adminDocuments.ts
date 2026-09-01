import {
  parseDocumentList,
  parseDocumentUploadResult,
  parseIngestionJob,
  type DocumentList,
  type DocumentUploadResult,
  type IngestionJob,
} from '../../../entities/document/model/contracts';
import { requestJson } from '../../../shared/api/requestJson';
import { API_ENDPOINTS } from '../../../shared/config/endpoints';

export interface UploadDocumentInput {
  file: File;
  title?: string;
  docType: 'literature' | 'clinical';
}

export function listDocuments(
  limit = 25,
  offset = 0,
  fetcher: typeof fetch = fetch,
): Promise<DocumentList> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requestJson(
    `${API_ENDPOINTS.adminDocuments}?${query}`,
    { fetcher },
    parseDocumentList,
  );
}

export function uploadDocument(
  input: UploadDocumentInput,
  fetcher: typeof fetch = fetch,
): Promise<DocumentUploadResult> {
  const body = new FormData();
  body.append('file', input.file, input.file.name);
  body.append('doc_type', input.docType);
  if (input.title?.trim()) {
    body.append('title', input.title.trim());
  }
  return requestJson(
    API_ENDPOINTS.adminDocuments,
    { method: 'POST', body, fetcher },
    parseDocumentUploadResult,
  );
}

export function getIngestionJob(
  jobId: string,
  fetcher: typeof fetch = fetch,
): Promise<IngestionJob> {
  return requestJson(API_ENDPOINTS.adminIngestionJob(jobId), { fetcher }, parseIngestionJob);
}

export function retryIngestionJob(
  jobId: string,
  fetcher: typeof fetch = fetch,
): Promise<IngestionJob> {
  return requestJson(
    API_ENDPOINTS.adminIngestionRetry(jobId),
    { method: 'POST', fetcher },
    parseIngestionJob,
  );
}

export function cancelIngestionJob(
  jobId: string,
  fetcher: typeof fetch = fetch,
): Promise<IngestionJob> {
  return requestJson(
    API_ENDPOINTS.adminIngestionCancel(jobId),
    { method: 'POST', fetcher },
    parseIngestionJob,
  );
}
