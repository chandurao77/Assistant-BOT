import { useEffect, useRef } from 'react';
import type { ChatMessage, FeedbackValue } from '@/types';
import { MessageItem } from './MessageItem';

interface Props {
  messages: ChatMessage[];
  isLoading: boolean;
  onSelectQuestion: (question: string) => void;
  onFeedback: (messageId: string, value: FeedbackValue, reason?: string | null, reasonText?: string | null) => void;
  onRetry: () => void;
  onAskAbout: (text: string) => void;
}

export function MessageList({ messages, isLoading, onSelectQuestion, onFeedback, onRetry, onAskAbout }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6"
           style={{ background: 'radial-gradient(ellipse at center, rgba(37,99,235,0.06) 0%, transparent 70%)' }}>
        {/* Gradient icon with glow */}
        <div className="w-16 h-16 bg-gradient-to-br from-blue-600 to-purple-600 rounded-2xl flex items-center 
                        justify-center mb-5 shadow-[0_8px_30px_rgba(37,99,235,0.35)] animate-glow">
          <svg
            className="w-8 h-8 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"
            />
          </svg>
        </div>
        <h2 className="text-[28px] font-heading font-semibold text-[#0f172a] dark:text-gray-100 mb-2">
          What can I help you find?
        </h2>
        <p className="text-sm text-[#64748b] dark:text-gray-400 max-w-md leading-relaxed">
          Ask me anything about your documents — handbooks, runbooks, guides, and more.
        </p>
        <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-w-lg w-full">
          {EXAMPLE_QUESTIONS.map((q) => (
            <ExampleQuestion key={q} text={q} onSelect={onSelectQuestion} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-5 space-y-5" role="log" aria-live="polite">
      <div className="max-w-4xl mx-auto space-y-5">
      {messages.map((msg) => (
        <MessageItem
          key={msg.id}
          message={msg}
          onFeedback={msg.role === 'assistant' ? onFeedback : undefined}
          onRetry={msg.role === 'assistant' && (msg.status === 'error' || (msg.status === 'complete' && !msg.content)) ? onRetry : undefined}
          onAskAbout={msg.role === 'assistant' && msg.status === 'complete' ? onAskAbout : undefined}
        />
      ))}
      </div>
      <div ref={bottomRef} />
    </div>
  );
}

const EXAMPLE_QUESTIONS = [
  'How do I set up the development environment?',
  'What is our incident response process?',
  'How do I deploy to staging?',
  'Where can I find onboarding docs?',
];

function ExampleQuestion({ text, onSelect }: { text: string; onSelect: (q: string) => void }) {
  return (
    <button
      onClick={() => onSelect(text)}
      className="group text-left px-4 py-3 rounded-2xl border border-[#e2e8f0] dark:border-gray-600/60 bg-white dark:bg-gray-750
                 hover:border-blue-400 dark:hover:border-blue-500 hover:shadow-[0_4px_20px_rgba(59,130,246,0.12)] dark:hover:bg-blue-900/20
                 text-sm text-gray-600 dark:text-gray-300 hover:text-blue-600 
                 transition-all duration-200 hover:-translate-y-0.5"
    >
      <span className="flex items-start gap-2">
        <svg className="w-4 h-4 mt-0.5 flex-shrink-0 text-gray-300 dark:text-gray-500 group-hover:text-blue-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {text}
      </span>
    </button>
  );
}
