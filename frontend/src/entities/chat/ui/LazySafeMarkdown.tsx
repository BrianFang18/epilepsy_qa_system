import { lazy, Suspense } from 'react';

const MarkdownContent = lazy(() =>
  import('./SafeMarkdown').then((module) => ({ default: module.SafeMarkdown })),
);

interface SafeMarkdownProps {
  children: string;
}

export function SafeMarkdown({ children }: SafeMarkdownProps) {
  return (
    <Suspense
      fallback={<p className="m-0 whitespace-pre-wrap break-words leading-7">{children}</p>}
    >
      <MarkdownContent>{children}</MarkdownContent>
    </Suspense>
  );
}
