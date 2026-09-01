import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import { useState, type ReactNode } from 'react';
import type { AdminDocument, IngestionJob } from '../../../entities/document/model/contracts';
import {
  documentKeys,
  selectFirstNonTerminalIngestionJob,
  useAdminDocuments,
  useIngestionJobWithRecovery,
} from './useAdminDocuments';

const JOB: IngestionJob = {
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

const DOCUMENT: AdminDocument = {
  id: 'document-1',
  filename: 'guide.md',
  title: 'Guide',
  doc_type: 'literature',
  media_type: 'text/markdown',
  size_bytes: 18,
  content_sha256: 'a'.repeat(64),
  status: 'processing',
  created_at: '2026-08-26T10:00:00Z',
  updated_at: '2026-08-26T10:00:00Z',
  indexed_at: null,
  latest_ingestion_job: JOB,
};

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function RecoveryHarness({
  initialActiveJobId = null,
}: {
  initialActiveJobId?: string | null;
}) {
  const documents = useAdminDocuments();
  const [activeJobId, setActiveJobId] = useState<string | null>(initialActiveJobId);
  const job = useIngestionJobWithRecovery(documents.data?.items, activeJobId, setActiveJobId);
  return (
    <>
      <span data-testid="active-job">{activeJobId ?? 'none'}</span>
      <span data-testid="job-status">{job.data?.status ?? 'none'}</span>
    </>
  );
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('admin document ingestion recovery', () => {
  it('selects the first non-terminal latest job in current-page order', () => {
    const terminalDocument: AdminDocument = {
      ...DOCUMENT,
      id: 'document-terminal',
      latest_ingestion_job: {
        ...JOB,
        id: 'job-terminal',
        document_id: 'document-terminal',
        status: 'failed',
      },
    };
    const laterActiveDocument: AdminDocument = {
      ...DOCUMENT,
      id: 'document-2',
      latest_ingestion_job: {
        ...JOB,
        id: 'job-2',
        document_id: 'document-2',
        status: 'running',
      },
    };

    expect(
      selectFirstNonTerminalIngestionJob([terminalDocument, DOCUMENT, laterActiveDocument])
        ?.id,
    ).toBe('job-1');
    expect(selectFirstNonTerminalIngestionJob([terminalDocument])).toBeNull();
    expect(selectFirstNonTerminalIngestionJob(undefined)).toBeNull();
  });

  it('seeds a fresh query cache, resumes polling after refresh, and stops at terminal status', async () => {
    const queryClient = createQueryClient();
    let jobRequests = 0;
    let resolveFirstJobRequest: ((response: Response) => void) | undefined;
    const firstJobRequest = new Promise<Response>((resolve) => {
      resolveFirstJobRequest = resolve;
    });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith('/api/v1/admin/documents?')) {
        return new Response(JSON.stringify({ items: [DOCUMENT], total: 1 }), {
          status: 200,
        });
      }
      if (url === '/api/v1/admin/ingestion-jobs/job-1') {
        jobRequests += 1;
        if (jobRequests === 1) {
          return firstJobRequest;
        }
        return new Response(
          JSON.stringify({
            ...JOB,
            status: 'succeeded',
            stage: 'finalize',
            progress: 100,
            finished_at: '2026-08-26T10:01:00Z',
          }),
          { status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<RecoveryHarness />, { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(screen.getByTestId('active-job')).toHaveTextContent('job-1'));
    await waitFor(() => expect(jobRequests).toBe(1));
    expect(queryClient.getQueryData(documentKeys.job('job-1'))).toEqual(JOB);

    await act(async () => {
      resolveFirstJobRequest?.(
        new Response(JSON.stringify({ ...JOB, status: 'running', progress: 30 }), {
          status: 200,
        }),
      );
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(screen.getByTestId('job-status')).toHaveTextContent('running'),
    );
    await waitFor(() => expect(jobRequests).toBe(2), { timeout: 2_500 });
    await waitFor(() =>
      expect(screen.getByTestId('job-status')).toHaveTextContent('succeeded'),
    );

    await new Promise((resolve) => setTimeout(resolve, 1_700));
    expect(jobRequests).toBe(2);
    expect(
      fetchMock.mock.calls.some(
        ([input]) => String(input) === '/api/v1/admin/ingestion-jobs/job-1',
      ),
    ).toBe(true);
  }, 7_000);

  it('keeps a current upload job ahead of a recoverable list job', async () => {
    const queryClient = createQueryClient();
    const uploadJob: IngestionJob = {
      ...JOB,
      id: 'upload-job',
      status: 'succeeded',
      stage: 'finalize',
      progress: 100,
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith('/api/v1/admin/documents?')) {
        return new Response(JSON.stringify({ items: [DOCUMENT], total: 1 }), { status: 200 });
      }
      if (url === '/api/v1/admin/ingestion-jobs/upload-job') {
        return new Response(JSON.stringify(uploadJob), { status: 200 });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<RecoveryHarness initialActiveJobId="upload-job" />, {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() =>
      expect(screen.getByTestId('job-status')).toHaveTextContent('succeeded'),
    );
    expect(screen.getByTestId('active-job')).toHaveTextContent('upload-job');
    expect(queryClient.getQueryData(documentKeys.job('job-1'))).toBeUndefined();
    expect(
      fetchMock.mock.calls.some(
        ([input]) => String(input) === '/api/v1/admin/ingestion-jobs/job-1',
      ),
    ).toBe(false);
  });
});
