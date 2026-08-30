import { SourceChips } from './SourceChips';
import type { Message } from '@/lib/types';

interface MessageBubbleProps {
  message: Message;
  citeSources: boolean;
  onOpenSource: (doc?: string) => void;
}

/** Renders **bold** spans within a single line of text. */
function renderInline(line: string, keyPrefix: string): React.ReactNode[] {
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>;
    }
    return <span key={`${keyPrefix}-${i}`}>{part}</span>;
  });
}

/**
 * Minimal formatter for assistant answers -- supports **bold** spans and
 * "1. " numbered list lines, since real backend answers can include both
 * (e.g. a comparison broken into numbered points). Deliberately not a full
 * markdown renderer/library -- just enough to match the reference's
 * "numbered list with bold term" example without pulling in a dependency.
 */
function FormattedText({ text }: { text: string }) {
  const lines = text.split('\n').filter((l) => l.trim().length > 0);
  const numberedPattern = /^(\d+)\.\s+(.*)$/;
  const isNumberedList = lines.length > 1 && lines.every((l) => numberedPattern.test(l) || l.trim() === '');

  if (isNumberedList) {
    return (
      <ol className="list-decimal space-y-1.5 pl-4">
        {lines.map((line, i) => {
          const match = line.match(numberedPattern);
          return <li key={i}>{renderInline(match ? match[2] : line, `l${i}`)}</li>;
        })}
      </ol>
    );
  }

  return (
    <>
      {lines.map((line, i) => (
        <p key={i} className={i > 0 ? 'mt-2' : undefined}>
          {renderInline(line, `p${i}`)}
        </p>
      ))}
    </>
  );
}

export function MessageBubble({ message, citeSources, onOpenSource }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const sources = citeSources ? message.sources ?? [] : [];

  return (
    <div className={`animate-fadeInUp flex flex-col gap-1.5 px-8 ${isUser ? 'items-end' : 'items-start'}`}>
      <span
        className={`flex items-center gap-1 text-[10.5px] font-bold uppercase tracking-[0.07em] ${
          isUser ? 'text-[#b7aec8]' : 'text-[#b7aec8]'
        }`}
      >
        {message.viaVoice && (
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4" />
          </svg>
        )}
        {isUser ? 'You' : 'Doc Assist'}
      </span>

      <div className={`flex max-w-[560px] flex-col gap-3 ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`px-4 py-3 text-[14.5px] leading-[1.55] text-[#2b2733] ${
            isUser
              ? 'max-w-[520px] rounded-[16px_16px_4px_16px] bg-[#f4eef2]'
              : 'max-w-[560px] rounded-[16px_16px_16px_4px] border border-[rgba(138,99,214,0.10)] px-[18px] py-[14px] leading-[1.6]'
          }`}
          style={
            isUser
              ? undefined
              : { background: 'linear-gradient(135deg,#faf1f8,#f1eefb)' }
          }
        >
          <FormattedText text={message.text} />
        </div>
        <SourceChips sources={sources} onOpenSource={onOpenSource} />
      </div>
    </div>
  );
}
