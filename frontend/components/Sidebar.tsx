'use client';

import type { HistoryGroup, SessionSummary } from '@/lib/types';

interface SidebarProps {
  history: HistoryGroup[];
  activeSessionId: string | null;
  onNewChat: () => void;
  onSelect: (item: SessionSummary) => void;
}

export function Sidebar({ history, activeSessionId, onNewChat, onSelect }: SidebarProps) {
  return (
    <div className="w-[260px] flex-shrink-0 overflow-y-auto border-r border-[#132521] bg-[#0A1412]/60 p-3 backdrop-blur-sm">
      <button
        onClick={onNewChat}
        className="mb-3.5 flex w-full items-center gap-2 rounded-[10px] border border-[#1B332D] bg-[#101E1B] px-3 py-2.5 text-[13px] font-semibold text-[#EDF2E6] shadow-sm transition-colors hover:bg-[#16302A]"
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M12 5v14M5 12h14" />
        </svg>
        New chat
      </button>

      {history.length === 0 && <div className="px-2 py-3 text-[12.5px] text-[#5C7A72]">No conversations yet.</div>}

      {history.map((grp) => (
        <div key={grp.group} className="mb-4">
          <div className="px-2 pb-1.5 text-[11px] font-bold uppercase tracking-[0.06em] text-[#4E6A62]">
            {grp.group}
          </div>
          {grp.items.map((item) => {
            const active = item.id === activeSessionId;
            const label = item.title || 'Untitled conversation';
            return (
              <button
                key={item.id}
                onClick={() => onSelect(item)}
                className={`mb-0.5 block w-full truncate rounded-lg border-l-2 px-2.5 py-2 text-left text-[13px] text-[#B7CAC3] transition-colors hover:bg-[#101E1B] ${
                  active ? 'border-[#5EEAD4] bg-[#173832]' : 'border-transparent bg-transparent'
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
