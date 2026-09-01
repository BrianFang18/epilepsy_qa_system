import { lazy, Suspense, useEffect, useState, type ComponentProps } from 'react';

const CitationDrawerContent = lazy(() =>
  import('./CitationDrawer').then((module) => ({ default: module.CitationDrawer })),
);

type CitationDrawerProps = ComponentProps<typeof CitationDrawerContent>;

export function CitationDrawer(props: CitationDrawerProps) {
  const [hasOpened, setHasOpened] = useState(props.open);

  useEffect(() => {
    if (props.open) setHasOpened(true);
  }, [props.open]);

  if (!props.open && !hasOpened) return null;

  return (
    <Suspense fallback={null}>
      <CitationDrawerContent {...props} />
    </Suspense>
  );
}
