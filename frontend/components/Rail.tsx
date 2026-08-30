'use client';

interface RailProps {
  sourcesOpen: boolean;
  onNewChat: () => void;
  onChatClick: () => void;
  onVoiceClick: () => void;
  onSourcesClick: () => void;
  onSettingsClick: () => void;
}

export function Rail({ sourcesOpen, onNewChat, onChatClick, onVoiceClick, onSourcesClick, onSettingsClick }: RailProps) {
  const chatActive = !sourcesOpen;

  return (
    <div className="relative z-[2] flex w-[76px] flex-shrink-0 flex-col items-center justify-between border-r border-[#132521] bg-[#0A1412]/80 py-5 backdrop-blur-sm">
      <div className="flex flex-col items-center gap-[22px]">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-[#8FEFDC] to-[#2FA98F] font-serif text-xl text-[#06201B]">
          D
        </div>

        <button
          onClick={onNewChat}
          title="New chat"
          className="flex h-10 w-10 items-center justify-center rounded-[10px] border border-[#1B332D] bg-[#101E1B] text-[#CFEAE3] transition-colors hover:bg-[#16302A]"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>

        <div className="h-px w-7 bg-[#1B332D]" />

        <button
          onClick={onChatClick}
          title="Chat"
          className={`flex h-10 w-10 items-center justify-center rounded-[10px] transition-colors hover:bg-[#16302A] ${
            chatActive ? 'bg-[#173832] text-[#5EEAD4]' : 'text-[#5C7A72]'
          }`}
        >
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        </button>

        <button
          onClick={onVoiceClick}
          title="Voice"
          className="flex h-10 w-10 items-center justify-center rounded-[10px] text-[#5C7A72] transition-colors hover:bg-[#16302A] hover:text-[#5EEAD4]"
        >
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4" />
          </svg>
        </button>

        <button
          onClick={onSourcesClick}
          title="Documents"
          className={`flex h-10 w-10 items-center justify-center rounded-[10px] transition-colors hover:bg-[#16302A] ${
            sourcesOpen ? 'bg-[#173832] text-[#5EEAD4]' : 'text-[#5C7A72]'
          }`}
        >
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <path d="M14 2v6h6" />
          </svg>
        </button>
      </div>

      <button
        onClick={onSettingsClick}
        title="Settings"
        className="flex h-10 w-10 items-center justify-center rounded-[10px] text-[#5C7A72] transition-colors hover:text-[#EDF2E6]"
      >
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>
    </div>
  );
}
