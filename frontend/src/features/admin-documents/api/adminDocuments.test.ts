import { ApiError } from '../../../shared/api/apiError';
import {
  cancelIngestionJob,
  getIngestionJob,
  listDocuments,
  retryIngestionJob,
  uploadDocument,
} from './adminDocuments';
const DOCUMENT = {
  id: 'document-1',
  filename: 'guide.md',
  title: 'Guide',
  doc_type: 'literature',
  media_type: 'text/markdown',
  size_bytes: 18,
  content_sha256: 'a'.repeat(64),
  status: 'queued',
  created_at: '2026-08-26T10:00:00Z',
  updated_at: '2026-08-26T10:00:00Z',
  indexed_at: null,
};
const JOB = {
  id: 'job-1',
  document_id: 'document-1',
  status: 'queued',
  stage: 'fetch',
  progress: 0,
  attempts: 0,
  max_attempts: 3,
  inserted_parents: 0,
  inserted_children: 0,
  error_code: null,
  error_message: null,
  created_at: '2026-08-26T10:00:00Z',
  updated_at: '2026-08-26T10:00:00Z',
  started_at: null,
  finished_at: null,
};
const DOCUMENT_WITH_NULL_JOB = { ...DOCUMENT, latest_ingestion_job: null };
const DOCUMENT_WITH_JOB = { ...DOCUMENT, latest_ingestion_job: JOB };
describe('admin document API', () => {
  it('parses document lists and multipart upload results', async () => {
    const listFetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ items: [DOCUMENT], total: 1 }), { status: 200 }),
      );
    const list = await listDocuments(25, 0, listFetcher);
    expect(list).toMatchObject({
      total: 1,
      items: [{ id: 'document-1', latest_ingestion_job: null }],
    });
    expect(String(listFetcher.mock.calls[0]?.[0])).toContain('limit=25&offset=0');
    const uploadFetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ document: DOCUMENT, ingestion_job: JOB, deduplicated: false }),
          { status: 201 },
        ),
      );
    const file = new File(['# epilepsy guide'], 'guide.md', { type: 'text/markdown' });
    const result = await uploadDocument(
      { file, title: 'Guide', docType: 'literature' },
      uploadFetcher,
    );
    expect(result.ingestion_job.id).toBe('job-1');
    const body = uploadFetcher.mock.calls[0]?.[1]?.body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get('file')).toBeInstanceOf(File);
    expect((body as FormData).get('doc_type')).toBe('literature');
  });
  it('accepts missing or null latest jobs and validates non-null latest jobs', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [DOCUMENT_WITH_NULL_JOB], total: 1 }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [DOCUMENT_WITH_JOB], total: 1 }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [{ ...DOCUMENT, latest_ingestion_job: {} }],
            total: 1,
          }),
          { status: 200 },
        ),
      );

    const nullJobList = await listDocuments(25, 0, fetcher);
    const populatedJobList = await listDocuments(25, 0, fetcher);
    expect(nullJobList.items[0]?.latest_ingestion_job).toBeNull();
    expect(populatedJobList.items[0]?.latest_ingestion_job).toEqual(JOB);

    const malformedError = await listDocuments(25, 0, fetcher).catch(
      (caught: unknown) => caught,
    );
    expect(malformedError).toBeInstanceOf(ApiError);
    expect(malformedError).toMatchObject({ code: 'INVALID_API_RESPONSE', status: 502 });
  });
  it('uses isolated job endpoints for polling, retry, and cancellation', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementation(async () => new Response(JSON.stringify(JOB), { status: 200 }));
    await getIngestionJob('job-1', fetcher);
    await retryIngestionJob('job-1', fetcher);
    await cancelIngestionJob('job-1', fetcher);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/admin/ingestion-jobs/job-1',
      '/api/v1/admin/ingestion-jobs/job-1/retry',
      '/api/v1/admin/ingestion-jobs/job-1/cancel',
    ]);
    expect(fetcher.mock.calls.map(([, init]) => init?.method)).toEqual([
      undefined,
      'POST',
      'POST',
    ]);
  });
  it('rejects incompatible server contracts without exposing parser details', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(JSON.stringify({ items: [{}], total: 1 }), { status: 200 }),
      );
    const error = await listDocuments(25, 0, fetcher).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: 'INVALID_API_RESPONSE', status: 502 });
  });
});
