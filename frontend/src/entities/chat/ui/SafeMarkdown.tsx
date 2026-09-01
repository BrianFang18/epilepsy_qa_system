import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface SafeMarkdownProps {
  children: string;
}

function safeUrlTransform(url: string): string {
  const normalized = url.trim();
  if (/^(https?:|mailto:)/i.test(normalized)) return normalized;
  if (/^(#|\.?\.\/|\/[^/])/i.test(normalized)) return normalized;
  return '';
}

const components: Components = {
  a: ({ children, href, title }) => {
    if (!href) return <span>{children}</span>;
    const external = /^https?:\/\//i.test(href);
    return (
      <a
        href={href}
        title={title}
        target={external ? '_blank' : undefined}
        rel={external ? 'noopener noreferrer' : undefined}
      >
        {children}
      </a>
    );
  },
  img: () => null,
};

export function SafeMarkdown({ children }: SafeMarkdownProps) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        components={components}
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={safeUrlTransform}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
