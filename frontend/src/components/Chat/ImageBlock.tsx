import { useEffect, useRef, useState } from 'react';

interface Props {
  src: string;
  alt: string;
}

export function ImageBlock({ src, alt }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  // Focus trap + Escape for image lightbox
  useEffect(() => {
    if (!expanded) return;
    closeBtnRef.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(false);
      if (e.key === 'Tab') { e.preventDefault(); closeBtnRef.current?.focus(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [expanded]);

  if (loadError) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2 py-1 my-1 rounded bg-gray-100 dark:bg-gray-700 text-xs text-gray-500 dark:text-gray-400">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        {alt || 'Image not available'}
      </div>
    );
  }

  return (
    <>
      <figure className="my-3">
        <img
          src={src}
          alt={alt}
          loading="lazy"
          onClick={() => setExpanded(true)}
          onError={() => setLoadError(true)}
          className="max-w-full max-h-80 rounded-lg border border-gray-200 dark:border-gray-600 
                     cursor-zoom-in hover:shadow-md transition-shadow duration-200 object-contain"
        />
        {alt && alt !== 'image' && (
          <figcaption className="text-[10px] text-gray-400 dark:text-gray-500 mt-1 italic">
            {alt}
          </figcaption>
        )}
      </figure>

      {/* Lightbox overlay */}
      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
          role="dialog"
          aria-modal="true"
          aria-label="Expanded image view"
          onClick={() => setExpanded(false)}
        >
          <button
            ref={closeBtnRef}
            onClick={() => setExpanded(false)}
            className="absolute top-4 right-4 text-white/80 hover:text-white transition-colors"
            aria-label="Close image"
          >
            <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
          <img
            src={src}
            alt={alt}
            className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}
