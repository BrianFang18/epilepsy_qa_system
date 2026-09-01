import { createEvaluation, getEvaluationSummary, listEvaluations } from './adminEvaluations';
const EVALUATION = {
  id: 'evaluation-1',
  name: 'Public smoke run',
  suite: 'smoke',
  status: 'succeeded',
  progress: 100,
  attempts: 1,
  max_attempts: 2,
  aggregate_metrics: { recall_at_5: 0.81 },
  error_code: null,
  error_message: null,
  created_at: '2026-08-26T10:00:00Z',
  updated_at: '2026-08-26T10:02:00Z',
  started_at: '2026-08-26T10:00:30Z',
  finished_at: '2026-08-26T10:02:00Z',
  private_result_object_key: 'must-not-reach-ui',
};
describe('admin evaluation API', () => {
  it('keeps only aggregate fields in parsed list and summary responses', async () => {
    const listFetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ items: [EVALUATION], total: 1 }), { status: 200 }),
      );
    const list = await listEvaluations(25, 0, listFetcher);
    expect(list.items[0]?.aggregate_metrics).toEqual({ recall_at_5: 0.81 });
    expect(list.items[0]).not.toHaveProperty('private_result_object_key');
    const summaryFetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          total: 1,
          status_counts: { succeeded: 1 },
          latest_metrics: { recall_at_5: 0.81 },
          latest_completed_at: '2026-08-26T10:02:00Z',
          private_answers: ['must-not-reach-ui'],
        }),
        { status: 200 },
      ),
    );
    const summary = await getEvaluationSummary(summaryFetcher);
    expect(summary.latest_metrics).toEqual({ recall_at_5: 0.81 });
    expect(summary).not.toHaveProperty('private_answers');
  });
  it('creates an evaluation with an explicit suite', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify(EVALUATION), { status: 202 }));
    const created = await createEvaluation(
      { name: 'Public smoke run', suite: 'smoke' },
      fetcher,
    );
    expect(created.id).toBe('evaluation-1');
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      name: 'Public smoke run',
      suite: 'smoke',
    });
  });
});
