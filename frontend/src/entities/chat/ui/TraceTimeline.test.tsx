import { render, screen } from '@testing-library/react';

import { TraceTimeline } from './TraceTimeline';

describe('TraceTimeline', () => {
  it('renders sorted public execution metadata without reasoning text', () => {
    render(
      <TraceTimeline
        entries={[
          {
            node: 'retrieve',
            status: 'completed',
            count: 3,
            duration_ms: 12.4,
            sequence: 3,
          },
          {
            node: 'input_emergency_guard',
            status: 'skipped',
            count: 0,
            duration_ms: 1,
            sequence: 1,
          },
        ]}
      />,
    );

    expect(screen.getByText('处理轨迹')).toBeInTheDocument();
    expect(screen.getByText('紧急风险筛查')).toBeInTheDocument();
    expect(screen.getByText('混合证据检索')).toBeInTheDocument();
    expect(screen.getByText('数量 3')).toBeInTheDocument();
    expect(screen.getByText('耗时 12 ms')).toBeInTheDocument();
    expect(screen.getByText(/不包含模型思维链/)).toBeInTheDocument();
  });
});
