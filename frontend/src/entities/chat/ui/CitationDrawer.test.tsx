import { render, screen } from '@testing-library/react';

import type { Citation } from '../model/contracts';
import { CitationDrawer } from './CitationDrawer';

const CITATIONS: Citation[] = [
  {
    id: 'C1',
    document_id: 'doc-1',
    title: 'Original title',
    translated_title: '中文证据标题',
    authors: ['Author A', 'Author B'],
    year: 2025,
    source_url: 'https://example.org/evidence',
    evidence_tier: 'A',
    excerpt: '可核验的证据摘录。',
    score: 0.9123,
  },
  {
    id: 'C2',
    document_id: 'doc-2',
    title: 'Local evidence',
    translated_title: null,
    authors: [],
    year: null,
    source_url: null,
    evidence_tier: 'Unrated',
    excerpt: '没有外链的本地证据。',
    score: 0.5,
  },
];

describe('CitationDrawer', () => {
  it('renders evidence metadata and protects external links', () => {
    render(<CitationDrawer open citations={CITATIONS} onClose={() => undefined} />);

    expect(screen.getByText('证据来源（2）')).toBeInTheDocument();
    expect(screen.getByText('中文证据标题')).toBeInTheDocument();
    expect(screen.getByText('Original title')).toBeInTheDocument();
    expect(screen.getByText('A 级证据')).toBeInTheDocument();
    expect(screen.getByText('未评级')).toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.getByRole('link', { name: '查看原始来源' })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    );
    expect(screen.getByRole('link', { name: '查看原始来源' })).toHaveAttribute(
      'target',
      '_blank',
    );
  });
});
