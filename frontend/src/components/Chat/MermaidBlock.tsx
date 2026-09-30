import { useEffect, useRef, useState, useCallback } from 'react';
import mermaid from 'mermaid';
import DOMPurify from 'dompurify';

// Initialize Mermaid once
mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'strict',
  fontFamily: 'Inter, system-ui, sans-serif',
  flowchart: { htmlLabels: true, curve: 'basis' },
  sequence: { actorMargin: 50, messageMargin: 40 },
});

interface Props {
  chart: string;
}

let mermaidCounter = 0;

export function MermaidBlock({ chart }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [expanded, setExpanded] = useState(false);
  const [zoom, setZoom] = useState(1);

  const zoomIn = useCallback(() => setZoom((z) => Math.min(z + 0.25, 4)), []);
  const zoomOut = useCallback(() => setZoom((z) => Math.max(z - 0.25, 0.25)), []);
  const zoomReset = useCallback(() => setZoom(1), []);

  useEffect(() => {
    const id = `mermaid-${++mermaidCounter}`;
    let cancelled = false;

    (async () => {
      try {
        const { svg: rendered } = await mermaid.render(id, chart.trim());
        if (!cancelled) {
          setSvg(DOMPurify.sanitize(rendered, { USE_PROFILES: { svg: true, svgFilters: true }, ADD_TAGS: ['foreignObject'] }));
          setError('');
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to render diagram');
          setSvg('');
        }
        // Clean up Mermaid's error container
        const el = document.getElementById(`d${id}`);
        el?.remove();
      }
    })();

    return () => { cancelled = true; };
  }, [chart]);

  // Close on Escape, reset zoom
  useEffect(() => {
    if (!expanded) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setExpanded(false); setZoom(1); }
      if (e.key === '+' || e.key === '=') zoomIn();
      if (e.key === '-') zoomOut();
      if (e.key === '0') zoomReset();
      // Trap focus inside lightbox
      if (e.key === 'Tab') {
        const focusable = document.querySelectorAll<HTMLElement>('.mermaid-lightbox button');
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    // Auto-focus the close button
    setTimeout(() => document.querySelector<HTMLElement>('.mermaid-lightbox button[aria-label="Close"]')?.focus(), 50);
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [expanded, zoomIn, zoomOut, zoomReset]);

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50 rounded-lg p-3 my-2">
        <p className="text-xs text-red-600 dark:text-red-400 font-medium mb-1">Diagram render error</p>
        <pre className="text-xs text-red-500 whitespace-pre-wrap">{error}</pre>
        <details className="mt-2">
          <summary className="text-xs text-gray-500 cursor-pointer">Show source</summary>
          <pre className="bg-gray-900 text-gray-100 rounded p-2 mt-1 text-xs overflow-x-auto">{chart}</pre>
        </details>
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="flex items-center justify-center py-4">
        <div className="w-5 h-5 border-2 border-confluence-blue border-t-transparent rounded-full animate-spin" />
        <span className="ml-2 text-xs text-gray-500">Rendering diagram...</span>
      </div>
    );
  }

  return (
    <>
      <div
        ref={containerRef}
        className="my-3 p-3 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-lg overflow-x-auto cursor-pointer group relative"
        onClick={() => setExpanded(true)}
        title="Click to expand"
      >
        <div dangerouslySetInnerHTML={{ __html: svg }} />
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-gray-800/70 text-white text-xs px-2 py-1 rounded">
          Click to expand
        </div>
      </div>

      {expanded && (
        <div
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm mermaid-lightbox"
          role="dialog"
          aria-modal="true"
          aria-label="Expanded diagram view"
          onClick={() => { setExpanded(false); setZoom(1); }}
          onWheel={(e) => { e.preventDefault(); if (e.deltaY < 0) { zoomIn(); } else { zoomOut(); } }}
        >
          {/* Toolbar — fixed at top */}
          <div
            className="absolute top-0 left-0 right-0 z-20 flex items-center justify-center gap-3 py-3 bg-black/60"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={zoomOut}
              className="px-3 py-1.5 text-sm bg-white/20 hover:bg-white/30 text-white rounded-lg"
              title="Zoom out (−)"
            >
              −
            </button>
            <span className="text-sm text-white/80 min-w-[3.5rem] text-center font-medium">
              {Math.round(zoom * 100)}%
            </span>
            <button
              onClick={zoomIn}
              className="px-3 py-1.5 text-sm bg-white/20 hover:bg-white/30 text-white rounded-lg"
              title="Zoom in (+)"
            >
              +
            </button>
            <button
              onClick={zoomReset}
              className="px-3 py-1.5 text-xs bg-white/20 hover:bg-white/30 text-white rounded-lg"
              title="Reset zoom (0)"
            >
              Reset
            </button>
            <button
              onClick={() => { setExpanded(false); setZoom(1); }}
              className="ml-4 px-3 py-1.5 text-sm bg-red-600/80 hover:bg-red-500 text-white rounded-lg"
              aria-label="Close"
            >
              ✕ Close
            </button>
          </div>

          {/* Diagram — fills the screen */}
          <div
            className="absolute inset-0 top-12 overflow-auto flex items-center justify-center p-4"
            onClick={(e) => e.stopPropagation()}
            onWheel={(e) => { e.stopPropagation(); if (e.deltaY < 0) { zoomIn(); } else { zoomOut(); } }}
          >
            <div
              className="bg-white dark:bg-gray-900 rounded-lg p-6 shadow-2xl [&_svg]:w-full [&_svg]:h-auto transition-transform duration-150"
              style={{ transform: `scale(${zoom})`, transformOrigin: 'center center' }}
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          </div>
        </div>
      )}
    </>
  );
}
