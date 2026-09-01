import { Button, Drawer, Empty, Tag, Typography } from 'antd';

import type { Citation, EvidenceTier } from '../model/contracts';

interface CitationDrawerProps {
  open: boolean;
  citations: readonly Citation[];
  onClose: () => void;
}

const TIER_LABELS: Record<EvidenceTier, string> = {
  A: 'A 级证据',
  B: 'B 级证据',
  C: 'C 级证据',
  Unrated: '未评级',
};

const TIER_COLORS: Record<EvidenceTier, string> = {
  A: 'green',
  B: 'blue',
  C: 'gold',
  Unrated: 'default',
};

export function CitationDrawer({ open, citations, onClose }: CitationDrawerProps) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="right"
      rootClassName="citation-drawer"
      size="default"
      title={`证据来源（${citations.length}）`}
    >
      {citations.length === 0 ? (
        <Empty description="本次回答没有可展示的证据来源" />
      ) : (
        <div className="space-y-4" aria-label="证据来源列表">
          {citations.map((citation) => (
            <article
              className="rounded-xl border border-slate-200 bg-slate-50 p-4"
              key={citation.id}
            >
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Tag color="cyan">{citation.id}</Tag>
                <Tag color={TIER_COLORS[citation.evidence_tier]}>
                  {TIER_LABELS[citation.evidence_tier]}
                </Tag>
                <Typography.Text type="secondary">
                  相关度 {citation.score.toFixed(3)}
                </Typography.Text>
              </div>
              <Typography.Title level={5} className="!mb-1 !mt-0">
                {citation.translated_title || citation.title}
              </Typography.Title>
              {citation.translated_title && citation.translated_title !== citation.title && (
                <Typography.Paragraph type="secondary" className="!mb-2">
                  {citation.title}
                </Typography.Paragraph>
              )}
              <Typography.Paragraph className="!mb-2 text-sm text-slate-600">
                {citation.authors.length > 0 ? citation.authors.join('、') : '作者未知'}
                {citation.year ? ` · ${citation.year}` : ''}
              </Typography.Paragraph>
              <blockquote className="m-0 border-l-4 border-teal-500 bg-white px-3 py-2 text-sm leading-6 text-slate-700">
                {citation.excerpt}
              </blockquote>
              {citation.source_url && (
                <Button
                  className="mt-3"
                  href={citation.source_url}
                  rel="noopener noreferrer"
                  target="_blank"
                  type="link"
                >
                  查看原始来源
                </Button>
              )}
            </article>
          ))}
        </div>
      )}
    </Drawer>
  );
}
