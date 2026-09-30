import { useState } from 'react';
import type { SourceDocument } from '@/types';
import { getSourceType } from '@/types';

interface Props {
  sources: SourceDocument[];
}

const SOURCE_BADGE: Record<string, { label: string; color: string; icon: string }> = {
  confluence: { label: 'Confluence', color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300', icon: '📄' },
  jira: { label: 'Jira', color: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300', icon: '🎫' },
  github: { label: 'GitHub', color: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300', icon: '🐙' },
  upload: { label: 'Upload', color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300', icon: '📎' },
};

function formatLastModified(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    const date = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return 'Updated today';
    if (diffDays === 1) return 'Updated yesterday';
    if (diffDays < 30) return `Updated ${diffDays}d ago`;
    if (diffDays < 365) return `Updated ${Math.floor(diffDays / 30)}mo ago`;
    return `Updated ${date.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}`;
  } catch {
    return null;
  }
}

export function SourceCitations({ sources }: Props) {
  const [open, setOpen] = useState(false);

  if (!sources.length) return null;

  return (
    <div className="mt-3 border-t border-gray-100 dark:border-gray-600 pt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide
                   hover:text-gray-700 dark:hover:text-gray-200 transition-colors w-full"
      >
        <svg
          className={`w-3 h-3 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        Sources ({sources.length})
      </button>

      {open && (
        <div className="flex flex-wrap gap-2 mt-2 animate-in fade-in slide-in-from-top-1 duration-200">
          {sources.map((src) => {
            const srcType = getSourceType(src);
            const badge = SOURCE_BADGE[srcType];
            return (
              <a
                key={src.page_id}
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex flex-col max-w-xs bg-confluence-lightBlue dark:bg-blue-900/30 hover:bg-blue-100 dark:hover:bg-blue-900/50
                           border border-blue-200 dark:border-blue-800 rounded-lg px-3 py-2 transition-colors duration-150"
              >
                <span className="text-xs font-medium text-confluence-blue dark:text-blue-400 group-hover:underline line-clamp-1">
                  {badge.icon} {src.title}
                </span>
                {src.excerpt && (
                  <p className="text-[10px] text-gray-500 dark:text-gray-400 line-clamp-2 mt-1 leading-snug">
                    {src.excerpt}
                  </p>
                )}
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <span className={`text-[10px] rounded px-1.5 py-0.5 font-medium ${badge.color}`}>
                    {badge.label}
                  </span>
                  <span className="text-[10px] text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600
                                   rounded px-1.5 py-0.5">
                    {src.space_key.startsWith('__') ? src.space_name : src.space_key}
                  </span>
                  <span className="text-[10px] text-gray-400 dark:text-gray-500">
                    {Math.round(src.score * 100)}% match
                  </span>
                  {formatLastModified(src.last_modified) && (
                    <span className="text-[10px] text-gray-400 dark:text-gray-500" title={src.last_modified ?? undefined}>
                      · {formatLastModified(src.last_modified)}
                    </span>
                  )}
                </div>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}
