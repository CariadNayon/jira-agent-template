"""Render fenced code and Mermaid diagrams in answers without lazily loaded chunks.

Streamdown loads its code and diagram renderers on demand. When such a chunk does not arrive,
the answer shows a spinner forever. The replacement below uses the frontend's own synchronous
code block and draws Mermaid diagrams with a bounded, failure-tolerant import: the source stays
visible until the drawing succeeds. Apply before building on each start.
"""
from pathlib import Path

_IMPORT_ANCHOR = "import { Streamdown } from 'streamdown';\n"
_IMPORT = "import { MarkdownCode } from './markdown-code';\n"
_COMPONENT_ANCHOR = "          a: DatabricksMessageCitationStreamdownIntegration,\n"
_COMPONENT = "          code: MarkdownCode,\n"

_SOURCE = """// Jira Agent: synchronous code blocks and Mermaid diagrams.
import {
  type ComponentProps,
  type ReactNode,
  isValidElement,
  useEffect,
  useId,
  useState,
} from 'react';
import { cn } from '@/lib/utils';
import { CodeBlock } from './code-block';

const LANGUAGE = /language-([^\\s]+)/;
const DRAW_DELAY_MS = 400;

function codeText(children: ReactNode): string {
  if (typeof children === 'string') return children;
  if (isValidElement(children)) {
    const inner = (children.props as { children?: unknown }).children;
    if (typeof inner === 'string') return inner;
  }
  return '';
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="rounded px-2 py-1 text-muted-foreground text-xs hover:bg-muted"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function MermaidDiagram({ chart }: { chart: string }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, '');
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Answers stream in piece by piece: draw only once the text stopped changing.
    const timer = setTimeout(async () => {
      try {
        const { default: mermaid } = await import('mermaid');
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: document.documentElement.classList.contains('dark')
            ? 'dark'
            : 'default',
        });
        const source = chart.trim();
        await mermaid.parse(source);
        const drawn = await mermaid.render(`mermaid-${id}-${Date.now()}`, source);
        if (!cancelled) {
          setSvg(drawn.svg);
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      }
    }, DRAW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [chart, id]);

  if (svg && !failed) {
    return (
      <div
        className="my-4 overflow-x-auto rounded-xl border p-4 [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full"
        data-testid="mermaid-diagram"
        // Mermaid's strict security level sanitizes labels and disables click handlers.
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    );
  }
  return (
    <div className="my-4">
      <CodeBlock code={chart.replace(/\\n$/, '')} language="text">
        <CopyButton text={chart} />
      </CodeBlock>
      {failed && (
        <p className="mt-1 text-muted-foreground text-xs">
          The diagram could not be drawn. Showing its source.
        </p>
      )}
    </div>
  );
}

type MarkdownCodeProps = ComponentProps<'code'> & {
  node?: { position?: { start: { line: number }; end: { line: number } } };
};

export function MarkdownCode({
  node,
  className,
  children,
  ...props
}: MarkdownCodeProps) {
  const position = node?.position;
  if (position && position.start.line === position.end.line) {
    return (
      <code
        className={cn('rounded bg-muted px-1.5 py-0.5 font-mono text-sm', className)}
        data-streamdown="inline-code"
        {...props}
      >
        {children}
      </code>
    );
  }
  const language = className?.match(LANGUAGE)?.[1] ?? '';
  const text = codeText(children);
  if (language === 'mermaid') return <MermaidDiagram chart={text} />;
  return (
    <div className="my-4">
      <CodeBlock code={text.replace(/\\n$/, '')} language={language || 'text'}>
        <CopyButton text={text.replace(/\\n$/, '')} />
      </CodeBlock>
    </div>
  );
}
"""


def ensure_frontend_markdown(frontend: Path) -> None:
    elements = frontend / 'client/src/components/elements'
    response = elements / 'response.tsx'
    source = response.read_text(encoding='utf-8')
    if _IMPORT not in source:
        if source.count(_IMPORT_ANCHOR) != 1 or source.count(_COMPONENT_ANCHOR) != 1:
            raise RuntimeError('Chat-Frontend geändert: Markdown-Darstellung vor dem Build prüfen.')
        source = source.replace(_IMPORT_ANCHOR, _IMPORT_ANCHOR + _IMPORT, 1)
        source = source.replace(_COMPONENT_ANCHOR, _COMPONENT_ANCHOR + _COMPONENT, 1)
        response.write_text(source, encoding='utf-8')
    (elements / 'markdown-code.tsx').write_text(_SOURCE, encoding='utf-8')
