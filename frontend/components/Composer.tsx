'use client';

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onAttach?: () => void;
  onTalk?: () => void;
  disabled?: boolean;
}

export function Composer({ value, onChange, onSend, onAttach, onTalk, disabled }: ComposerProps) {
  return (
    <div
      className="flex items-center gap-2.5 rounded-[18px] border border-[rgba(30,20,45,0.10)] bg-white py-2 pl-[18px] pr-2 shadow-[0_2px_10px_rgba(30,20,45,0.05)]"
    >
      {onAttach && (
        <button
          onClick={onAttach}
          title="Attach a policy document"
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-[#9a93a8] transition-colors duration-200 ease-out hover:bg-[rgba(138,99,214,0.08)] hover:text-[#6d4bb8]"
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <path d="M17 8l-5-5-5 5M12 3v12" />
          </svg>
        </button>
      )}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onSend();
        }}
        placeholder="Ask about a policy, benefit, or process…"
        disabled={disabled}
        className="flex-1 bg-transparent px-1 text-[14.5px] text-[#2b2733] outline-none placeholder:text-[#9a93a8]"
      />
      {onTalk && (
        <button
          onClick={onTalk}
          title="Talk"
          className="flex flex-shrink-0 items-center gap-[7px] whitespace-nowrap rounded-[14px] px-[15px] py-[9px] text-[13px] font-semibold text-white"
          style={{ background: 'linear-gradient(135deg,#9b7fe0,#e79bd0)' }}
        >
          <svg viewBox="0 0 20 24" width="13" height="15" fill="#fff">
            <rect x="1" y="8" width="3" height="8" rx="1.5" />
            <rect x="8" y="3" width="3" height="18" rx="1.5" />
            <rect x="15" y="6" width="3" height="12" rx="1.5" />
          </svg>
          Talk
        </button>
      )}
      <button
        onClick={onSend}
        title="Send"
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-[#6d4bb8] transition-opacity hover:opacity-90"
      >
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 12L20 4l-6.5 16-3-6.5L4 12z" />
        </svg>
      </button>
    </div>
  );
}
