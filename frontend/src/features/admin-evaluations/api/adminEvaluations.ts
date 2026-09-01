import {
  parseEvaluationJob,
  parseEvaluationList,
  parseEvaluationSummary,
  type EvaluationJob,
  type EvaluationList,
  type EvaluationSuite,
  type EvaluationSummary,
} from '../../../entities/evaluation/model/contracts';
import { jsonBody, requestJson } from '../../../shared/api/requestJson';
import { API_ENDPOINTS } from '../../../shared/config/endpoints';

export interface CreateEvaluationInput {
  name: string;
  suite: EvaluationSuite;
}

export function listEvaluations(
  limit = 25,
  offset = 0,
  fetcher: typeof fetch = fetch,
): Promise<EvaluationList> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requestJson(
    `${API_ENDPOINTS.adminEvaluations}?${query}`,
    { fetcher },
    parseEvaluationList,
  );
}

export function getEvaluationSummary(
  fetcher: typeof fetch = fetch,
): Promise<EvaluationSummary> {
  return requestJson(
    API_ENDPOINTS.adminEvaluationSummary,
    { fetcher },
    parseEvaluationSummary,
  );
}

export function createEvaluation(
  input: CreateEvaluationInput,
  fetcher: typeof fetch = fetch,
): Promise<EvaluationJob> {
  return requestJson(
    API_ENDPOINTS.adminEvaluations,
    { method: 'POST', fetcher, ...jsonBody(input) },
    parseEvaluationJob,
  );
}
