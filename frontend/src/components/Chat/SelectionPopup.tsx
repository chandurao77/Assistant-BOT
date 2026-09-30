import { useEffect, useRef, useState } from 'react';

interface PopupState {
  text: string;
  x: number;
  y: number;
}

interface Props {
  containerRef: React.RefObject<HTMLDivElement | null>;
  onAskAbout: (text: string) => void;
}

export function SelectionPopup({ containerRef, onAskAbout }: Props) {
  const [popup, setPopup] = useState<PopupState | null>(null);
  const [copied, setCopied] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    function handleMouseUp() {
      // Small delay to let the browser finalise the selection
      setTimeout(() => {
        const sel = window.getSelection();
        const text = sel?.toString().trim();
        if (!text || !sel || sel.rangeCount === 0) {
          setPopup(null);
          return;
        }
        const range = sel.getRangeAt(0);
        const el = containerRef.current;
        // Only show popup when selection is inside this message
        if (!el || !el.contains(range.commonAncestorContainer)) {
          setPopup(null);
          return;
        }
        const rect = range.getBoundingClientRect();
        setPopup({
          text,
          x: rect.left + rect.width / 2,
          y: rect.top,
        });
      }, 10);
    }

    function handleMouseDown(e: MouseEvent) {
      // Keep popup alive while clicking inside it
      if (popupRef.current?.contains(e.target as Node)) return;
      setPopup(null);
    }

    function handleSelectionChange() {
      if (!window.getSelection()?.toString().trim()) setPopup(null);
    }

    container.addEventListener('mouseup', handleMouseUp);
    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('selectionchange', handleSelectionChange);

    return () => {
      container.removeEventListener('mouseup', handleMouseUp);
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('selectionchange', handleSelectionChange);
    };
  }, [containerRef]);

  if (!popup) return null;

  function handleAsk() {
    if (!popup) return;
    onAskAbout(`Tell me more about: "${popup.text}"`);
    window.getSelection()?.removeAllRanges();
    setPopup(null);
  }

  function handleCopy() {
    if (!popup) return;
    navigator.clipboard.writeText(popup.text).catch(() => {});
    setCopied(true);
    setTimeout(() => {
      setCopied(false);
      setPopup(null);
      window.getSelection()?.removeAllRanges();
    }, 1000);
  }

  return (
    <div
      ref={popupRef}
      style={{
        position: 'fixed',
        left: popup.x,
        top: popup.y,
        transform: 'translate(-50%, calc(-100% - 10px))',
        zIndex: 1000,
      }}
      // Stop mousedown propagating so the "hide on outside click" handler ignores it
      onMouseDown={(e) => e.stopPropagation()}
      className="flex items-center bg-gray-900 rounded-lg shadow-2xl px-1 py-1 animate-fade-in"
    >
      <button
        onClick={handleAsk}
        className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-white
                   hover:bg-gray-700 rounded-md transition-colors font-medium whitespace-nowrap"
        title="Ask the assistant about this selection"
      >
        <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
        </svg>
        Ask Assistant
      </button>

      <div className="w-px h-4 bg-gray-600 mx-0.5" />

      <button
        onClick={handleCopy}
        className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-gray-300
                   hover:bg-gray-700 rounded-md transition-colors whitespace-nowrap"
        title="Copy selected text"
      >
        {copied ? (
          <>
            <svg className="w-3.5 h-3.5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <span className="text-green-400">Copied</span>
          </>
        ) : (
          <>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            Copy
          </>
        )}
      </button>

      {/* Downward arrow caret */}
      <div
        style={{
          position: 'absolute',
          bottom: -4,
          left: '50%',
          transform: 'translateX(-50%) rotate(45deg)',
          width: 8,
          height: 8,
          backgroundColor: '#111827',
        }}
      />
    </div>
  );
}
