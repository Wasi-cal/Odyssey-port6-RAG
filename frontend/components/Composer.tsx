'use client';

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onAttach?: () => void;
  disabled?: boolean;
}

export function Composer({ value, onChange, onSend, onAttach, disabled }: ComposerProps) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-[#1B332D] bg-[#101E1B] py-2 pl-3 pr-2 shadow-[0_8px_24px_rgba(0,0,0,0.35)]">
      {onAttach && (
        <button
          onClick={onAttach}
          title="Attach a policy document"
          className="flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-full text-[#5C7A72] transition-colors hover:bg-[#173832] hover:text-[#5EEAD4]"
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
        placeholder="Type something…"
        disabled={disabled}
        className="flex-1 bg-transparent px-1 text-[15px] text-[#EDF2E6] outline-none placeholder:text-[#4E6A62]"
      />
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
  );
}
