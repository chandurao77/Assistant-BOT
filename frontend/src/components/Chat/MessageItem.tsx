import { useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage, FeedbackValue, NegativeFeedbackReason } from '@/types';
import { SourceCitations } from './SourceCitations';
import { SelectionPopup } from './SelectionPopup';
import { MermaidBlock } from './MermaidBlock';
import { ImageBlock } from './ImageBlock';
import { useAuth } from '@/contexts/AuthContext';

const NEGATIVE_REASONS: { value: NegativeFeedbackReason; label: string }[] = [
  { value: 'outdated_information', label: 'Outdated information' },
  { value: 'wrong_answer', label: 'Wrong answer' },
  { value: 'incomplete_answer', label: 'Incomplete answer' },
  { value: 'not_relevant', label: 'Not relevant' },
  { value: 'other', label: 'Other' },
];

interface Props {
  message: ChatMessage;
  onFeedback?: (messageId: string, value: FeedbackValue, reason?: string | null, reasonText?: string | null) => void;
  onRetry?: () => void;
  onAskAbout?: (text: string) => void;
}

export function MessageItem({ message, onFeedback, onRetry, onAskAbout }: Props) {
  const contentRef = useRef<HTMLDivElement>(null);
  const { user } = useAuth();
  const isUser = message.role === 'user';
  const isStreaming = message.status === 'streaming';
  const isError = message.status === 'error';
  const [showReasonPicker, setShowReasonPicker] = useState(false);
  const [selectedReason, setSelectedReason] = useState<NegativeFeedbackReason | null>(null);
  const [reasonText, setReasonText] = useState('');

  const handleThumbsDown = () => {
    if (message.feedback === -1) {
      // Toggle off — clear reason state
      setShowReasonPicker(false);
      setSelectedReason(null);
      setReasonText('');
      onFeedback?.(message.id, null);
    } else {
      // Show reason picker
      setShowReasonPicker(true);
    }
  };

  const handleReasonSubmit = () => {
    if (!selectedReason) return;
    onFeedback?.(message.id, -1, selectedReason, selectedReason === 'other' ? reasonText : null);
    setShowReasonPicker(false);
  };

  const handleReasonCancel = () => {
    setShowReasonPicker(false);
    setSelectedReason(null);
    setReasonText('');
  };

  return (
    <div
      className={`flex w-full animate-fade-in ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      {/* Avatar */}
      {!isUser && (
        <div className="flex-shrink-0 mr-3 mt-1 flex flex-col items-center">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-confluence-blue to-blue-600 flex items-center 
                          justify-center text-white shadow-sm">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
            </svg>
          </div>
        </div>
      )}

      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-gradient-to-br from-confluence-blue to-blue-600 text-white rounded-br-md shadow-md shadow-blue-500/10'
            : isError
            ? 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/50 text-red-800 dark:text-red-300 rounded-bl-md'
            : 'bg-white dark:bg-gray-750 border border-gray-200/80 dark:border-gray-600/50 text-gray-800 dark:text-gray-100 rounded-bl-md shadow-sm'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
        ) : (
          <div ref={contentRef} className="text-sm leading-relaxed">
            {onAskAbout && !isStreaming && (
              <SelectionPopup containerRef={contentRef} onAskAbout={onAskAbout} />
            )}
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ className, children, ...props }) {
                  const match = className?.match(/language-(\w+)/);
                  const lang = match?.[1];
                  const codeStr = String(children).replace(/\n$/, '');

                  // Render Mermaid diagrams as interactive SVG
                  if (lang === 'mermaid') {
                    return <MermaidBlock chart={codeStr} />;
                  }

                  const isBlock = !!lang;
                  return isBlock ? (
                    <div className="relative group my-2">
                      {lang && (
                        <span className="absolute top-1.5 right-2 text-[10px] text-gray-500 uppercase tracking-wide opacity-60">
                          {lang}
                        </span>
                      )}
                      <pre className="bg-gray-900 text-gray-100 rounded-lg p-3 overflow-x-auto text-xs">
                        <code className={className} {...props}>
                          {children}
                        </code>
                      </pre>
                    </div>
                  ) : (
                    <code
                      className="bg-gray-100 dark:bg-gray-600 text-red-600 dark:text-red-400 rounded px-1 py-0.5 text-xs font-mono"
                      {...props}
                    >
                      {children}
                    </code>
                  );
                },
                img({ src, alt }) {
                  if (!src) return null;
                  return <ImageBlock src={src} alt={alt || 'image'} />;
                },
                table({ children }) {
                  return (
                    <div className="overflow-x-auto my-2">
                      <table className="min-w-full text-xs border-collapse border border-gray-200 dark:border-gray-600 rounded">
                        {children}
                      </table>
                    </div>
                  );
                },
                thead({ children }) {
                  return <thead className="bg-gray-50 dark:bg-gray-700">{children}</thead>;
                },
                th({ children }) {
                  return (
                    <th className="px-3 py-1.5 text-left text-xs font-semibold text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-600">
                      {children}
                    </th>
                  );
                },
                td({ children }) {
                  return (
                    <td className="px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-600">
                      {children}
                    </td>
                  );
                },
                p({ children }) {
                  return <p className="mb-2 last:mb-0">{children}</p>;
                },
                ul({ children }) {
                  return <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>;
                },
                ol({ children }) {
                  return <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>;
                },
                li({ children }) {
                  return <li className="text-sm">{children}</li>;
                },
                strong({ children }) {
                  return <strong className="font-semibold text-gray-900 dark:text-gray-100">{children}</strong>;
                },
                h1({ children }) {
                  return <h1 className="text-base font-bold mb-2 mt-3">{children}</h1>;
                },
                h2({ children }) {
                  return <h2 className="text-sm font-bold mb-1 mt-2">{children}</h2>;
                },
                h3({ children }) {
                  return <h3 className="text-sm font-semibold mb-1 mt-2">{children}</h3>;
                },
              }}
            >
              {message.content || (isStreaming ? '' : '_No response received._')}
            </ReactMarkdown>

            {/* Streaming cursor */}
            {isStreaming && (
              <span className="inline-block w-1.5 h-4 bg-confluence-blue rounded-sm ml-0.5 
                               animate-pulse-dot align-middle" />
            )}

            {/* Source citations */}
            {message.sources && message.sources.length > 0 && !isStreaming && (
              <>
                {message.confidence && (
                  <div className="flex items-center gap-1.5 mt-2 mb-1">
                    <span className="text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">Confidence</span>
                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                      message.confidence === 'high'
                        ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400'
                        : message.confidence === 'medium'
                        ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400'
                        : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400'
                    }`}>
                      {message.confidence}
                    </span>
                  </div>
                )}
                <SourceCitations sources={message.sources} />
              </>
            )}

            {/* Feedback buttons — only on complete assistant messages */}
            {!isStreaming && !isError && onFeedback && (
              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-600">
                <div className="flex items-center gap-1">
                  <span className="text-[10px] text-gray-400 mr-1">Helpful?</span>
                  <FeedbackButton
                    active={message.feedback === 1}
                    onClick={() =>
                      onFeedback(message.id, message.feedback === 1 ? null : 1)
                    }
                    title="Helpful"
                  >
                    <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                      <path d="M2 10.5a1.5 1.5 0 113 0v6a1.5 1.5 0 01-3 0v-6zM6 10.333v5.43a2 2 0 001.106 1.79l.05.025A4 4 0 008.943 18h5.416a2 2 0 001.962-1.608l1.2-6A2 2 0 0015.56 8H12V4a2 2 0 00-2-2 1 1 0 00-1 1v.667a4 4 0 01-.8 2.4L6.8 7.933a4 4 0 00-.8 2.4z" />
                    </svg>
                  </FeedbackButton>
                  <FeedbackButton
                    active={message.feedback === -1}
                    onClick={handleThumbsDown}
                    title="Not helpful"
                    negative
                  >
                    <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                      <path d="M18 9.5a1.5 1.5 0 11-3 0v-6a1.5 1.5 0 013 0v6zM14 9.667v-5.43a2 2 0 00-1.105-1.79l-.05-.025A4 4 0 0011.055 2H5.64a2 2 0 00-1.962 1.608l-1.2 6A2 2 0 004.44 12H8v4a2 2 0 002 2 1 1 0 001-1v-.667a4 4 0 01.8-2.4l1.4-1.866a4 4 0 00.8-2.4z" />
                    </svg>
                  </FeedbackButton>

                  <span className="mx-1 w-px h-3.5 bg-gray-200 dark:bg-gray-600" />
                  <CopyButton text={message.content} />
                </div>

                {/* Reason picker — shown after thumbs down */}
                {showReasonPicker && (
                  <div className="mt-2 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg border border-gray-200 dark:border-gray-600 animate-fade-in">
                    <p className="text-xs font-medium text-gray-600 dark:text-gray-300 mb-2">What went wrong?</p>
                    <div className="flex flex-col gap-1.5">
                      {NEGATIVE_REASONS.map((r) => (
                        <label
                          key={r.value}
                          className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer text-xs transition-colors ${
                            selectedReason === r.value
                              ? 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800'
                              : 'hover:bg-gray-100 dark:hover:bg-gray-600/50 text-gray-600 dark:text-gray-400'
                          }`}
                        >
                          <input
                            type="radio"
                            name={`reason-${message.id}`}
                            value={r.value}
                            checked={selectedReason === r.value}
                            onChange={() => setSelectedReason(r.value)}
                            className="w-3 h-3 text-red-500 accent-red-500"
                          />
                          {r.label}
                          {r.value === 'outdated_information' && selectedReason === r.value && (
                            <span className="ml-auto text-[10px] text-amber-600 dark:text-amber-400 font-medium">
                              Will re-ingest sources
                            </span>
                          )}
                        </label>
                      ))}
                    </div>
                    {selectedReason === 'other' && (
                      <textarea
                        value={reasonText}
                        onChange={(e) => setReasonText(e.target.value)}
                        placeholder="Please describe the issue..."
                        maxLength={500}
                        rows={2}
                        className="mt-2 w-full text-xs px-2 py-1.5 rounded-md border border-gray-200 dark:border-gray-600 
                                   bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 
                                   placeholder-gray-400 dark:placeholder-gray-500 resize-none
                                   focus:outline-none focus:ring-1 focus:ring-red-300 dark:focus:ring-red-700"
                      />
                    )}
                    <div className="flex gap-2 mt-2">
                      <button
                        onClick={handleReasonSubmit}
                        disabled={!selectedReason || (selectedReason === 'other' && !reasonText.trim())}
                        className="px-3 py-1 text-xs font-medium rounded-md bg-red-500 text-white
                                   hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      >
                        Submit
                      </button>
                      <button
                        onClick={handleReasonCancel}
                        className="px-3 py-1 text-xs font-medium rounded-md text-gray-500 dark:text-gray-400
                                   hover:bg-gray-100 dark:hover:bg-gray-600/50 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Retry button — on error or empty responses */}
            {(isError || (!isStreaming && !message.content)) && onRetry && (
              <div className="mt-2 pt-2 border-t border-red-100 dark:border-red-800">
                <button
                  onClick={onRetry}
                  className="flex items-center gap-1 text-xs text-red-600 hover:text-red-800 
                             transition-colors font-medium"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  Retry
                </button>
              </div>
            )}
          </div>
        )}

        {/* Timestamp */}
        <p className={`text-[10px] mt-1.5 ${isUser ? 'text-blue-200' : 'text-gray-400 dark:text-gray-500'} text-right`}>
          {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>

      {isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-xl bg-gradient-to-br from-gray-400 to-gray-500 dark:from-gray-500 dark:to-gray-600 flex items-center 
                        justify-center text-white text-xs font-bold ml-3 mt-1 shadow-sm">
          {user?.name?.charAt(0)?.toUpperCase() || 'U'}
        </div>
      )}
    </div>
  );
}

function FeedbackButton({
  children,
  active,
  negative,
  onClick,
  title,
}: {
  children: React.ReactNode;
  active: boolean;
  negative?: boolean;
  onClick: () => void;
  title: string;
}) {
  const activeClass = negative
    ? 'text-red-500 bg-red-50 dark:bg-red-900/30'
    : 'text-green-600 bg-green-50 dark:bg-green-900/30';

  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className={`p-1 rounded transition-colors ${
        active ? activeClass : 'text-gray-300 dark:text-gray-500 hover:text-gray-500 dark:hover:text-gray-300'
      }`}
    >
      {children}
    </button>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      onClick={handleCopy}
      title={copied ? 'Copied!' : 'Copy response'}
      aria-label="Copy response"
      className={`p-1 rounded transition-colors ${
        copied ? 'text-green-500' : 'text-gray-300 hover:text-gray-500'
      }`}
    >
      {copied ? (
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      )}
    </button>
  );
}
