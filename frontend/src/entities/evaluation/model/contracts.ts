import {
  asArray,
  asEnum,
  asNumber,
  asOptionalString,
  asRecord,
  asString,
} from '../../../shared/api/contract';
import { JOB_STATUSES, type JobStatus } from '../../document/model/contracts';

export const EVALUATION_SUITES = [
  'smoke',
  'retrieval',
  'generation',
  'safety',
  'full',
] as const;
export type EvaluationSuite = (typeof EVALUATION_SUITES)[number];

export interface EvaluationJob {
  id: string;
  name: string;
  suite: EvaluationSuite;
  status: JobStatus;
  progress: number;
  attempts: number;
  max_attempts: number;
  aggregate_metrics: Record<string, number>;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EvaluationList {
  items: EvaluationJob[];
  total: number;
}

export interface EvaluationSummary {
  total: number;
  status_counts: Record<string, number>;
  latest_metrics: Record<string, number>;
  latest_completed_at: string | null;
}

function parseNumberRecord(value: unknown, field: string): Record<string, number> {
  const source = asRecord(value);
  return Object.fromEntries(
    Object.entries(source).map(([key, item]) => [key, asNumber(item, `${field}.${key}`)]),
  );
}

export function parseEvaluationJob(value: unknown): EvaluationJob {
  const root = asRecord(value);
  return {
    id: asString(root.id, 'evaluation.id'),
    name: asString(root.name, 'evaluation.name'),
    suite: asEnum(root.suite, EVALUATION_SUITES, 'evaluation.suite'),
    status: asEnum(root.status, JOB_STATUSES, 'evaluation.status'),
    progress: asNumber(root.progress, 'evaluation.progress'),
    attempts: asNumber(root.attempts, 'evaluation.attempts'),
    max_attempts: asNumber(root.max_attempts, 'evaluation.max_attempts'),
    aggregate_metrics: parseNumberRecord(root.aggregate_metrics, 'aggregate_metrics'),
    error_code: asOptionalString(root.error_code, 'evaluation.error_code'),
    error_message: asOptionalString(root.error_message, 'evaluation.error_message'),
    created_at: asString(root.created_at, 'evaluation.created_at'),
    updated_at: asString(root.updated_at, 'evaluation.updated_at'),
    started_at: asOptionalString(root.started_at, 'evaluation.started_at'),
    finished_at: asOptionalString(root.finished_at, 'evaluation.finished_at'),
  };
}

export function parseEvaluationList(value: unknown): EvaluationList {
  const root = asRecord(value);
  return {
    items: asArray(root.items, 'items').map(parseEvaluationJob),
    total: asNumber(root.total, 'total'),
  };
}

export function parseEvaluationSummary(value: unknown): EvaluationSummary {
  const root = asRecord(value);
  return {
    total: asNumber(root.total, 'summary.total'),
    status_counts: parseNumberRecord(root.status_counts, 'status_counts'),
    latest_metrics: parseNumberRecord(root.latest_metrics, 'latest_metrics'),
    latest_completed_at: asOptionalString(root.latest_completed_at, 'latest_completed_at'),
  };
}
