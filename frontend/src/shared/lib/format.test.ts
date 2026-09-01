import { formatBytes, formatDateTime, formatMetric } from './format';

describe('admin presentation formatters', () => {
  it('formats sizes and aggregate metrics without exposing raw objects', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(2 * 1024 * 1024)).toBe('2.0 MB');
    expect(formatMetric(1)).toBe('1');
    expect(formatMetric(0.81234)).toBe('0.812');
  });

  it('handles missing and malformed dates safely', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime('not-a-date')).toBe('—');
    expect(formatDateTime('2026-08-26T10:00:00Z')).not.toBe('—');
  });
});
