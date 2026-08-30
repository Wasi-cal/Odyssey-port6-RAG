'use client';

import { useRef } from 'react';
import { LiquidSphere } from './LiquidSphere';
import { SHORTCUT_PROMPTS, PROMPT_CATEGORIES, CATEGORY_PROMPTS } from '@/hooks/useDocAssist';

interface HeroEmptyProps {
  onToggleListen: () => void;
  onPickSuggestion: (q: string) => void;
  uploadHint: string;
  onUpload: () => void;
  inputValue: string;
  onInputChange: (v: string) => void;
  onSend: () => void;
  activeCategory: (typeof PROMPT_CATEGORIES)[number];
  onCategoryChange: (c: (typeof PROMPT_CATEGORIES)[number]) => void;
}

const SHORTCUT_ICONS: Record<string, React.ReactNode> = {
  search: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  ),
  leave: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </svg>
  ),
};

export function HeroEmpty({
  onToggleListen,
  onPickSuggestion,
  uploadHint,
  onUpload,
  inputValue,
  onInputChange,
  onSend,
  activeCategory,
  onCategoryChange,
}: HeroEmptyProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);

  return (
    <div className="relative flex flex-1 flex-col overflow-y-auto p-8">
      <div className="mx-auto w-full max-w-[640px]">
        {/* Hero card */}
        <div
          className="relative overflow-hidden rounded-[28px] border border-[#1F3B34] p-7 pb-8"
          style={{ background: 'linear-gradient(135deg, #17332D 0%, #0E211D 70%)' }}
        >
          <div className="relative z-[1] max-w-[62%]">
            <div className="text-[11px] font-bold uppercase tracking-[0.1em] text-[#5EEAD4]">AI Assistant</div>
            <div className="mt-2 font-serif text-[28px] leading-[1.15] text-[#F4FAF8]">
              What Can I Help You With Today?
            </div>
            <button
              onClick={() => inputRef.current?.focus()}
              className="mt-6 flex items-center gap-2 rounded-full bg-[#F4FAF8] px-4 py-2.5 text-[13px] font-semibold text-[#0A1412] transition-opacity hover:opacity-90"
            >
              Ask Doc Assist
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </button>
          </div>
          <div className="pointer-events-none absolute -right-8 -bottom-10 opacity-90">
            <LiquidSphere size="180px" />
          </div>
        </div>

        {/* Shortcut tiles */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          {SHORTCUT_PROMPTS.map((s) => (
            <button
              key={s.title}
              onClick={() => onPickSuggestion(s.q)}
              className="flex items-center gap-3 rounded-2xl border border-[#1B332D] bg-[#101E1B] p-3.5 text-left transition-colors hover:border-[#2FA98F] hover:bg-[#132621]"
            >
              <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-[#173832] text-[#5EEAD4]">
                {SHORTCUT_ICONS[s.icon]}
              </span>
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-[#EDF2E6]">{s.title}</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0 text-[#4E6A62]">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
          ))}
        </div>

        {/* Popular prompts */}
        <div className="mt-7 flex items-center justify-between">
          <span className="text-[13px] font-bold text-[#EDF2E6]">Popular Prompts</span>
        </div>
        <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
          {PROMPT_CATEGORIES.map((c) => {
            const active = c === activeCategory;
            return (
              <button
                key={c}
                onClick={() => onCategoryChange(c)}
                className={`flex-shrink-0 rounded-full px-3.5 py-1.5 text-[12.5px] font-semibold transition-colors ${
                  active ? 'bg-[#5EEAD4] text-[#06201B]' : 'bg-[#101E1B] text-[#B7CAC3] hover:bg-[#173832]'
                }`}
              >
                {c}
              </button>
            );
          })}
        </div>
        <div className="mt-3 flex flex-col gap-2">
          {CATEGORY_PROMPTS[activeCategory].map((p) => (
            <button
              key={p.title}
              onClick={() => onPickSuggestion(p.q)}
              className="flex items-center gap-3 rounded-xl border border-[#1B332D] bg-[#0F1B18] px-3.5 py-3 text-left transition-colors hover:border-[#2FA98F] hover:bg-[#132621]"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0 text-[#5EEAD4]">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
              <span className="min-w-0 flex-1 truncate text-[13px] text-[#DCE8E3]">{p.title}</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0 text-[#4E6A62]">
                <path d="m9 18 6-6-6-6" />
              </svg>
            </button>
          ))}
        </div>

        {/* Composer */}
        <div className="mt-7 flex items-center gap-2 rounded-full border border-[#1B332D] bg-[#101E1B] py-2 pl-3 pr-2 shadow-[0_8px_24px_rgba(0,0,0,0.35)]">
          <button
            onClick={onUpload}
            title="Attach a policy document"
            className="flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-full text-[#5C7A72] transition-colors hover:bg-[#173832] hover:text-[#5EEAD4]"
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <path d="M17 8l-5-5-5 5M12 3v12" />
            </svg>
          </button>
          <input
            ref={inputRef}
            value={inputValue}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSend();
            }}
            placeholder="Type something…"
            className="flex-1 bg-transparent px-1 text-[15px] text-[#EDF2E6] outline-none placeholder:text-[#4E6A62]"
          />
          <button
            onClick={onToggleListen}
            title="Ask by voice"
            className="flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-full text-[#5C7A72] transition-colors hover:bg-[#173832] hover:text-[#5EEAD4]"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4" />
            </svg>
          </button>
          <button
            onClick={onSend}
            title="Send"
            className="flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-full bg-[#5EEAD4] text-[#06201B] transition-colors hover:bg-[#48D9C1]"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 2 11 13" />
              <path d="M22 2 15 22l-4-9-9-4 20-7z" />
            </svg>
          </button>
        </div>
        {uploading_hint_visible(uploadHint) && (
          <div className="mt-2 text-center text-[12px] text-[#5C7A72]">{uploadHint}</div>
        )}
      </div>
    </div>
  );
}

function uploading_hint_visible(hint: string) {
  return hint.toLowerCase().includes('uploading');
}
