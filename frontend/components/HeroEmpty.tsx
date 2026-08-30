'use client';

import { PROMPT_CATEGORIES, CATEGORY_PROMPTS } from '@/hooks/useDocAssist';

interface HeroEmptyProps {
  onPickSuggestion: (q: string) => void;
  activeCategory: (typeof PROMPT_CATEGORIES)[number];
  onCategoryChange: (c: (typeof PROMPT_CATEGORIES)[number]) => void;
}

const SPARKLE_PATH =
  'M12 2c.4 3.2 1.4 5.6 3 7.2 1.6 1.6 4 2.6 7 3-3 .4-5.4 1.4-7 3-1.6 1.6-2.6 4-3 7.2-.4-3.2-1.4-5.6-3-7.2-1.6-1.6-4-2.6-7-3 3-.4 5.4-1.4 7-3 1.6-1.6 2.6-4 3-7.2z';

/**
 * Welcome / empty state -- centered column matching the HR Chatbot design
 * handoff's "Welcome (empty) state" spec. The category tabs + prompt list
 * are real app functionality (see hooks/useDocAssist's PROMPT_CATEGORIES /
 * CATEGORY_PROMPTS), restyled as the design's pill tabs and suggestion
 * pills rather than invented content. The composer itself lives in
 * Workspace.tsx now (always visible, matching the design's input bar,
 * which sits outside the welcome/chat conditional).
 */
export function HeroEmpty({ onPickSuggestion, activeCategory, onCategoryChange }: HeroEmptyProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-10 text-center">
      <svg viewBox="0 0 24 24" width="36" height="36" fill="#6d4bb8">
        <path d={SPARKLE_PATH} />
      </svg>
      <div className="text-[30px] font-bold leading-tight tracking-[-0.01em] text-[#211f2b]">
        Ask me about company policies
      </div>
      <div className="max-w-[380px] text-[14.5px] text-[#7d7690]">
        Leave, payroll, travel, IT & security — I&rsquo;ve got the details, and I can talk it through too.
      </div>

      <div className="mt-1.5 flex flex-wrap justify-center gap-2">
        {PROMPT_CATEGORIES.map((c) => {
          const active = c === activeCategory;
          return (
            <button
              key={c}
              onClick={() => onCategoryChange(c)}
              className={`rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors ${
                active ? 'bg-[#6d4bb8] text-white' : 'bg-white text-[#5b5566] hover:bg-[rgba(138,99,214,0.08)]'
              }`}
              style={active ? undefined : { border: '1px solid rgba(30,20,45,0.10)' }}
            >
              {c}
            </button>
          );
        })}
      </div>

      <div className="mt-1.5 flex max-w-[520px] flex-wrap justify-center gap-2.5">
        {CATEGORY_PROMPTS[activeCategory].map((p) => (
          <button
            key={p.title}
            onClick={() => onPickSuggestion(p.q)}
            className="rounded-[20px] border border-[rgba(30,20,45,0.10)] bg-white px-4 py-[9px] text-[13px] font-medium text-[#433d55] transition-colors hover:bg-[rgba(138,99,214,0.06)]"
          >
            {p.title}
          </button>
        ))}
      </div>
    </div>
  );
}
