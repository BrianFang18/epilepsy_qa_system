import { render, screen } from '@testing-library/react';

import { SafeMarkdown } from './SafeMarkdown';

describe('SafeMarkdown', () => {
  it('drops raw HTML and images while securing external links', () => {
    render(
      <SafeMarkdown>{`[可信来源](https://example.org) [危险链接](javascript:alert(1))

<script>secret()</script>

![tracking](https://tracker.invalid/pixel.png)`}</SafeMarkdown>,
    );

    expect(screen.getByRole('link', { name: '可信来源' })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    );
    expect(screen.getByRole('link', { name: '可信来源' })).toHaveAttribute(
      'target',
      '_blank',
    );
    expect(screen.getByText('危险链接').closest('a')).toBeNull();
    expect(screen.queryByText('secret()')).not.toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});
