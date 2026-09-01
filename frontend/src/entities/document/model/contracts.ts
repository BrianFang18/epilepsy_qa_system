import {
  asArray,
  asBoolean,
  asEnum,
  asNumber,
  asOptionalString,
  asRecord,
  asString,
} from '../../../shared/api/contract';

export const DOCUMENT_STATUSES = [
  'uploaded',
  'queued',
  'processing',
  'active',
  'failed',
  'canceled',
] as const;
export const JOB_STATUSES = [
  'queued',
  'running',
  'retry_wait',
  'succeeded',
  'failed',
  'canceled',
] as const;
export const JOB_STAGES = ['fetch', 'parse', 'chunk', 'embed', 'index', 'finalize'] as const;

export type DocumentStatus = (typeof DOCUMENT_STATUSES)[number];
export type JobStatus = (typeof JOB_STATUSES)[number];
export type JobStage = (typeof JOB_STAGES)[number];

export interface AdminDocument {
  id: string;
  filename: string;
  title: string;
  doc_type: 'literature' | 'clinical';
  media_type: string;
  size_bytes: number;
  content_sha256: string;
  status: DocumentStatus;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
  latest_ingestion_job: IngestionJob | null;
}

export interface IngestionJob {
  id: string;
  document_id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
  attempts: number;
  max_attempts: number;
  inserted_parents: number;
  inserted_children: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface DocumentUploadResult {
  document: AdminDocument;
  ingestion_job: IngestionJob;
  deduplicated: boolean;
}

export interface DocumentList {
  items: AdminDocument[];
  total: number;
}

export function parseAdminDocument(value: unknown): AdminDocument {
  const root = asRecord(value);
  return {
    id: asString(root.id, 'document.id'),
    filename: asString(root.filename, 'document.filename'),
    title: asString(root.title, 'document.title'),
    doc_type: asEnum(root.doc_type, ['literature', 'clinical'] as const, 'document.doc_type'),
    media_type: asString(root.media_type, 'document.media_type'),
    size_bytes: asNumber(root.size_bytes, 'document.size_bytes'),
    content_sha256: asString(root.content_sha256, 'document.content_sha256'),
    status: asEnum(root.status, DOCUMENT_STATUSES, 'document.status'),
    created_at: asString(root.created_at, 'document.created_at'),
    updated_at: asString(root.updated_at, 'document.updated_at'),
    indexed_at: asOptionalString(root.indexed_at, 'document.indexed_at'),
    latest_ingestion_job:
      root.latest_ingestion_job === undefined || root.latest_ingestion_job === null
        ? null
        : parseIngestionJob(root.latest_ingestion_job),
  };
}

export function parseIngestionJob(value: unknown): IngestionJob {
  const root = asRecord(value);
  return {
    id: asString(root.id, 'job.id'),
    document_id: asString(root.document_id, 'job.document_id'),
    status: asEnum(root.status, JOB_STATUSES, 'job.status'),
    stage: asEnum(root.stage, JOB_STAGES, 'job.stage'),
    progress: asNumber(root.progress, 'job.progress'),
    attempts: asNumber(root.attempts, 'job.attempts'),
    max_attempts: asNumber(root.max_attempts, 'job.max_attempts'),
    inserted_parents: asNumber(root.inserted_parents, 'job.inserted_parents'),
    inserted_children: asNumber(root.inserted_children, 'job.inserted_children'),
    error_code: asOptionalString(root.error_code, 'job.error_code'),
    error_message: asOptionalString(root.error_message, 'job.error_message'),
    created_at: asString(root.created_at, 'job.created_at'),
    updated_at: asString(root.updated_at, 'job.updated_at'),
    started_at: asOptionalString(root.started_at, 'job.started_at'),
    finished_at: asOptionalString(root.finished_at, 'job.finished_at'),
  };
}

export function parseDocumentUploadResult(value: unknown): DocumentUploadResult {
  const root = asRecord(value);
  return {
    document: parseAdminDocument(root.document),
    ingestion_job: parseIngestionJob(root.ingestion_job),
    deduplicated: asBoolean(root.deduplicated, 'deduplicated'),
  };
}

export function parseDocumentList(value: unknown): DocumentList {
  const root = asRecord(value);
  return {
    items: asArray(root.items, 'items').map(parseAdminDocument),
    total: asNumber(root.total, 'total'),
  };
}

export function isTerminalJob(status: JobStatus): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'canceled';
}
