import { type KeyboardEvent, useRef, useState } from 'react';
import type { UploadedFile } from '@/types';

const ALLOWED_EXTENSIONS = ['.txt', '.md', '.pdf', '.docx'];
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

interface Props {
  onSend: (message: string) => void;
  onStop: () => void;
  onUpload: (file: File) => Promise<void>;
  isLoading: boolean;
  uploadedFiles: UploadedFile[];
  onRemoveUpload: (uploadId: string) => void;
  isUploading: boolean;
}

export function ChatInput({ onSend, onStop, onUpload, isLoading, uploadedFiles, onRemoveUpload, isUploading }: Props) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    onSend(trimmed);
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  const handleFileSelect = async () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset input so re-selecting the same file triggers onChange
    e.target.value = '';

    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      alert(`Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(', ')}`);
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      alert('File too large. Maximum size is 10 MB.');
      return;
    }
    await onUpload(file);
  };

  return (
    <div className="bg-white dark:bg-gray-800 px-4 py-3 transition-colors">
      {/* Uploaded file chips */}
      {uploadedFiles.length > 0 && (
        <div className="flex flex-wrap gap-2 max-w-4xl mx-auto mb-2">
          {uploadedFiles.map((f) => (
            <span
              key={f.upload_id}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium
                         bg-blue-50 dark:bg-blue-900/40 text-blue-600 dark:text-blue-300
                         border border-blue-200/50 dark:border-blue-700/40"
            >
              <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
              {f.filename}
              <span className="text-[10px] opacity-60">({f.chunks} chunks)</span>
              <button
                onClick={() => onRemoveUpload(f.upload_id)}
                className="ml-0.5 hover:text-red-500 transition-colors"
                title="Remove file"
                aria-label={`Remove ${f.filename}`}
              >
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2 max-w-4xl mx-auto">
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.md,.pdf,.docx"
          onChange={handleFileChange}
          className="hidden"
          aria-hidden="true"
        />

        {/* Upload button */}
        <button
          onClick={handleFileSelect}
          disabled={isUploading}
          className="flex-shrink-0 w-11 h-11 rounded-xl border border-[#e5e5e5] dark:border-gray-600
                     hover:border-blue-400 hover:text-blue-600 dark:hover:border-blue-400 dark:hover:text-blue-400
                     flex items-center justify-center transition-all duration-150
                     disabled:opacity-40 disabled:cursor-not-allowed
                     text-[#64748b] dark:text-gray-400"
          title="Upload a file (.txt, .md, .pdf, .docx)"
          aria-label="Upload a file"
        >
          {isUploading ? (
            <svg className="w-4.5 h-4.5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          )}
        </button>

        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            placeholder="Ask Assistant Bot anything about your documentation..."
            aria-label="Ask a question about your documentation"
            rows={1}
            disabled={false}
            className="w-full resize-none rounded-2xl border-[1.5px] border-[#e5e5e5] dark:border-gray-600 bg-white dark:bg-gray-700
                       px-4 py-3 pr-12 text-sm text-[#0f172a] dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500
                       focus:outline-none focus:border-blue-500 focus:shadow-[0_0_0_4px_rgba(59,130,246,0.15)]
                       disabled:opacity-50 max-h-[200px] overflow-y-auto transition-all"
          />
          <span className="absolute bottom-3 right-3 text-[10px] text-gray-300 dark:text-gray-600 select-none font-mono">
            ↵
          </span>
        </div>

        {isLoading ? (
          <button
            onClick={onStop}
            className="flex-shrink-0 w-11 h-11 rounded-2xl bg-red-500 hover:bg-red-600 
                       flex items-center justify-center transition-all duration-150 shadow-sm active:scale-95"
            title="Stop generating"
            aria-label="Stop generating"
          >
            <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" rx="2" />
            </svg>
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!input.trim()}
            className="flex-shrink-0 w-11 h-11 rounded-full bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700
                       disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center 
                       transition-all duration-150 shadow-md hover:shadow-lg active:scale-95 disabled:shadow-none"
            title="Send message (Enter)"
            aria-label="Send message"
          >
            <svg
              className="w-5 h-5 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19V5m-7 7l7-7 7 7"
              />
            </svg>
          </button>
        )}
      </div>
      <p className="text-center text-[11px] text-gray-400 dark:text-gray-500 mt-2">
        AI-generated answers from your documentation · Sources cited automatically
      </p>
    </div>
  );
}
