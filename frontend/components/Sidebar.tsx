'use client';

import { SHORTCUT_PROMPTS } from '@/hooks/useDocAssist';
import type { HistoryGroup, SessionSummary } from '@/lib/types';

interface SidebarProps {
  history: HistoryGroup[];
  activeSessionId: string | null;
  sourcesOpen: boolean;
  username: string;
  userInitials: string;
  onNewChat: () => void;
  onSelect: (item: SessionSummary) => void;
  onPickShortcut: (q: string) => void;
  onToggleSources: () => void;
  onOpenSettings: () => void;
  onLogout: () => void;
}

const SPARKLE_PATH =
  'M12 2c.4 3.2 1.4 5.6 3 7.2 1.6 1.6 4 2.6 7 3-3 .4-5.4 1.4-7 3-1.6 1.6-2.6 4-3 7.2-.4-3.2-1.4-5.6-3-7.2-1.6-1.6-4-2.6-7-3 3-.4 5.4-1.4 7-3 1.6-1.6 2.6-4 3-7.2z';

/**
 * Frosted 272px sidebar per the HR Chatbot design handoff -- brand row,
 * New chat button, scrollable Quick Links + Recent history, pinned user
 * profile row. Consolidates the previous Rail (icon strip) + Sidebar
 * (history list) + TopBar (brand/logout) into one component to match the
 * design's single-sidebar layout; Settings and the Documents/Sources
 * panel toggle -- real features with no dedicated design affordance --
 * are added here as small icon buttons alongside the brand row and the
 * New chat button.
 */
export function Sidebar({
  history,
  activeSessionId,
  sourcesOpen,
  username,
  userInitials,
  onNewChat,
  onSelect,
  onPickShortcut,
  onToggleSources,
  onOpenSettings,
  onLogout,
}: SidebarProps) {
  return (
    <aside
      className="flex h-full w-[272px] flex-shrink-0 flex-col gap-4 overflow-hidden border-r border-[rgba(30,20,45,0.07)] pt-[22px]"
      style={{ background: 'rgba(255,255,255,0.55)', backdropFilter: 'blur(16px)' }}
    >
      <div className="flex flex-shrink-0 items-center justify-between gap-2 px-4">
        <div className="flex items-center gap-[9px] px-1">
          <svg viewBox="0 0 24 24" width="19" height="19" fill="#6d4bb8">
            <path d={SPARKLE_PATH} />
          </svg>
          <span className="text-[15px] font-bold tracking-[-0.01em] text-[#211f2b]">Doc Assist</span>
        </div>
        <button
          onClick={onOpenSettings}
          title="Settings"
          className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-[#9a93a8] transition-colors duration-200 ease-out hover:bg-[rgba(138,99,214,0.08)] hover:text-[#6d4bb8]"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
      </div>

      <div className="flex flex-shrink-0 items-center gap-2 px-4">
        <button
          onClick={onNewChat}
          className="flex flex-1 items-center gap-2 rounded-xl border border-[rgba(30,20,45,0.08)] bg-white px-3.5 py-2.5 text-[13px] font-semibold text-[#3a3550] shadow-[0_1px_2px_rgba(30,20,45,0.04)] transition-colors duration-200 ease-out hover:bg-[#faf6fd]"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#3a3550" strokeWidth="2" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New chat
        </button>
        <button
          onClick={onToggleSources}
          title="Documents"
          className={`flex h-[38px] w-[38px] flex-shrink-0 items-center justify-center rounded-xl border transition-colors duration-200 ease-out ${
            sourcesOpen
              ? 'border-[rgba(138,99,214,0.25)] bg-[rgba(138,99,214,0.10)] text-[#6d4bb8]'
              : 'border-[rgba(30,20,45,0.08)] bg-white text-[#433d55] hover:bg-[#faf6fd]'
          }`}
        >
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
            <path d="M14 3v4h4" />
          </svg>
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-4">
        <div>
          <div className="mb-2 px-1 text-[11px] font-bold uppercase tracking-[0.06em] text-[#9a93a8]">Quick links</div>
          <div className="flex flex-col gap-0.5">
            {SHORTCUT_PROMPTS.map((s) => (
              <button
                key={s.title}
                onClick={() => onPickShortcut(s.q)}
                className="flex items-center gap-2.5 rounded-[10px] px-2.5 py-[9px] text-left text-[13px] font-medium text-[#433d55] transition-colors duration-200 ease-out hover:bg-[rgba(138,99,214,0.08)]"
              >
                <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-[rgba(138,99,214,0.10)]">
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#6d4bb8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
                    <path d="M14 3v4h4" />
                  </svg>
                </span>
                <span className="min-w-0 flex-1 truncate">{s.title}</span>
                <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="#b7aec8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="mb-2 px-1 text-[11px] font-bold uppercase tracking-[0.06em] text-[#9a93a8]">Recent</div>
          {history.length === 0 && <div className="px-2.5 py-1 text-[12.5px] text-[#9a93a8]">No conversations yet.</div>}
          {history.map((grp) => (
            <div key={grp.group} className="mb-2 flex flex-col gap-0.5">
              {grp.items.map((item) => {
                const active = item.id === activeSessionId;
                const label = item.title || 'Untitled conversation';
                return (
                  <button
                    key={item.id}
                    onClick={() => onSelect(item)}
                    className="flex flex-col gap-0.5 rounded-[10px] px-2.5 py-[9px] text-left transition-colors duration-200 ease-out"
                    style={{
                      background: active ? 'rgba(138,99,214,0.10)' : 'transparent',
                      color: active ? '#4a2f8a' : '#433d55',
                    }}
                  >
                    <div className="truncate text-[13px] font-semibold">{label}</div>
                    <div className="text-[11.5px] text-[#9a93a8]">{grp.group}</div>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      <button
        onClick={onLogout}
        title="Sign out"
        className="flex flex-shrink-0 items-center gap-2.5 border-t border-[rgba(30,20,45,0.06)] px-4 py-4 text-left transition-colors duration-200 ease-out hover:bg-[rgba(138,99,214,0.05)]"
      >
        <div
          className="flex h-[34px] w-[34px] flex-shrink-0 items-center justify-center rounded-full text-[13px] font-bold text-white"
          style={{ background: 'linear-gradient(135deg,#9b7fe0,#e79bd0)' }}
        >
          {userInitials}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold text-[#211f2b]">{username}</div>
          <div className="text-[11.5px] text-[#9a93a8]">Workspace member</div>
        </div>
      </button>
    </aside>
  );
}
