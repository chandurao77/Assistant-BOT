import { useEffect, useState } from 'react';
import { fetchSuggestions } from '@/services/api';

interface Props {
  currentQuestion?: string;
  onSelect: (question: string) => void;
  visible: boolean;
}

export function QuerySuggestions({ currentQuestion, onSelect, visible }: Props) {
  const [suggestions, setSuggestions] = useState<string[]>([]);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    fetchSuggestions(currentQuestion).then((s) => {
      if (!cancelled) setSuggestions(s);
    });
    return () => { cancelled = true; };
  }, [currentQuestion, visible]);

  if (!visible || suggestions.length === 0) return null;

  return (
    <div className="px-4 pb-3 bg-white dark:bg-gray-800">
      <p className="text-xs text-[#64748b] dark:text-gray-400 mb-1.5 font-medium">
        People also asked
      </p>
      <div className="flex flex-wrap gap-1.5">
        {suggestions.map((q) => (
          <button
            key={q}
            onClick={() => onSelect(q)}
            className="text-xs px-3 py-1.5 rounded-full border border-[#e5e5e5] dark:border-gray-600 
                       text-gray-600 dark:text-gray-300 hover:bg-[#f0f4ff] dark:hover:bg-blue-900/30 
                       hover:border-blue-400 hover:text-blue-600 transition-all duration-150"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
