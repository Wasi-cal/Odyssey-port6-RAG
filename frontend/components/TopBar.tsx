interface TopBarProps {
  companyName: string;
  userInitials: string;
  onLogout: () => void;
}

export function TopBar({ companyName, userInitials, onLogout }: TopBarProps) {
  return (
    <div className="relative z-[2] flex h-16 flex-shrink-0 items-center justify-between border-b border-[#132521] bg-[#0A1412]/70 px-7 backdrop-blur-sm">
      <div className="flex items-center gap-2">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-[#5EEAD4]">
          <path
            d="M9.94 15.5a2 2 0 0 0-1.44-1.44L2.36 12.48a.5.5 0 0 1 0-.96l6.14-1.58A2 2 0 0 0 9.94 8.5l1.58-6.14a.5.5 0 0 1 .96 0l1.58 6.14a2 2 0 0 0 1.44 1.44l6.14 1.58a.5.5 0 0 1 0 .96l-6.14 1.58a2 2 0 0 0-1.44 1.44l-1.58 6.14a.5.5 0 0 1-.96 0z"
            fill="currentColor"
          />
        </svg>
        <span className="font-serif text-[20px] leading-none tracking-[-0.01em] text-[#EDF2E6]">{companyName}</span>
      </div>
      <button
        onClick={onLogout}
        title="Sign out"
        className="flex h-[34px] w-[34px] items-center justify-center rounded-full bg-[#173832] text-[13px] font-bold text-[#5EEAD4] transition-opacity hover:opacity-80"
      >
        {userInitials}
      </button>
    </div>
  );
}
