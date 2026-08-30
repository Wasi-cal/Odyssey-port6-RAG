import type { SourceInfo } from '@/lib/types';

interface SourceChipsProps {
  sources: SourceInfo[];
  onOpenSource: (doc?: string) => void;
  className?: string;
}

/**
 * Citation chip row -- shared between MessageBubble (text chat) and
 * VoiceScreen (voice tool-call results). Citations are never spoken by the
 * realtime model (see prompt.py's <voice_response_style> / backend/api.py's
 * _VOICE_SESSION_INSTRUCTIONS), but the same on-screen rendering applies
 * either way, so this is the one place that renders a citation chip.
 */
export function SourceChips({ sources, onOpenSource, className }: SourceChipsProps) {
  if (sources.length === 0) return null;
  return (
    <div className={`flex flex-wrap gap-2 ${className ?? ''}`}>
      {sources.map((s, i) => (
        <button
          key={`${s.filename}-${s.page}-${i}`}
          onClick={() => onOpenSource(s.filename)}
          className="flex items-center gap-1.5 rounded-full border border-[rgba(30,20,45,0.12)] bg-white px-3.5 py-[7px] text-[12.5px] font-medium text-[#5b5566] transition-colors hover:border-[#6d4bb8]/40 hover:text-[#6d4bb8]"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <path d="M14 2v6h6" />
          </svg>
          {s.label}
        </button>
      ))}
    </div>
  );
}
