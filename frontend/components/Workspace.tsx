'use client';

import { useEffect, useState } from 'react';
import { useDocAssist } from '@/hooks/useDocAssist';
import { useAuth } from '@/lib/auth-context';
import { Sidebar } from './Sidebar';
import { SourcesPanel } from './SourcesPanel';
import { SettingsModal } from './SettingsModal';
import { Composer } from './Composer';
import { HeroEmpty } from './HeroEmpty';
import { DockedThread } from './DockedThread';
import { VoiceOverlay } from './VoiceOverlay';
import { GradientBackdrop } from './GradientBackdrop';

const SIDEBAR_COLLAPSED_KEY = 'docassist.sidebarCollapsed';

export function Workspace() {
  const d = useDocAssist();
  const { username, logout } = useAuth();

  const voiceActive = d.voiceStatus !== 'idle';
  const hasMessages = d.messages.length > 0;
  const showHero = !hasMessages;

  const initials = (username || '?').slice(0, 2).toUpperCase();

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  useEffect(() => {
    try {
      setSidebarCollapsed(localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1');
    } catch {
      // localStorage unavailable (private browsing, etc.) -- default expanded.
    }
  }, []);
  const toggleSidebarCollapsed = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? '1' : '0');
      } catch {
        // Best-effort; the preference just won't survive a reload.
      }
      return next;
    });
  };

  return (
    <div className="relative flex h-screen w-full overflow-hidden text-[#211f2b]">
      <GradientBackdrop />

      <input
        ref={d.fileInputRef}
        type="file"
        accept="application/pdf"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files) d.uploadFiles(e.target.files);
          e.target.value = '';
        }}
      />

      <div className="relative z-[1] flex h-full w-full">
        <Sidebar
          history={d.history}
          activeSessionId={d.activeHistoryTitle}
          sourcesOpen={d.sourcesOpen}
          username={username || ''}
          userInitials={initials}
          collapsed={sidebarCollapsed}
          onNewChat={d.newChat}
          onSelect={d.selectHistoryItem}
          onToggleSources={d.toggleSources}
          onOpenSettings={d.openSettings}
          onToggleCollapsed={toggleSidebarCollapsed}
          onLogout={logout}
        />

        <main className="relative flex min-w-0 flex-1 flex-col">
          {/* Errors are logged to the console (see useDocAssist.ts's
              catch blocks and the voice.error effect), not surfaced as a
              UI banner here anymore -- per request, they were noisy/non-
              actionable for the user (benign server-side voice messages,
              self-resolving races, etc.) more often than genuinely
              needing attention. */}

          <div className="relative flex min-h-0 flex-1">
            <div className="relative flex min-w-0 flex-1 flex-col">
              <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden px-8">
                {/* key swap (hero <-> thread) + animate-fadeInUp gives the
                    welcome/chat view switch the same soft entrance every
                    other new-content moment in this app uses (message
                    bubbles, the sources panel) instead of an instant,
                    jarring pop -- bug #5's "make view switches smooth". */}
                {showHero ? (
                  <HeroEmpty
                    key="hero"
                    onPickSuggestion={d.sendMessage}
                    activeCategory={d.activeCategory}
                    onCategoryChange={d.setActiveCategory}
                  />
                ) : (
                  <DockedThread
                    key={d.activeHistoryTitle ?? 'new'}
                    messages={d.messages}
                    citeSources={d.citeSources}
                    onOpenSource={d.openSource}
                  />
                )}
              </div>

              <div className="flex-shrink-0 px-8 pb-6 pt-4">
                <Composer
                  value={d.inputText}
                  onChange={d.setInputText}
                  onSend={d.onComposerSend}
                  onAttach={d.triggerUpload}
                  onTalk={d.toggleListen}
                  disabled={d.sending}
                />
                {d.uploading && <div className="mt-2 text-center text-[12px] text-[#9a93a8]">Uploading…</div>}
              </div>
            </div>

            {d.sourcesOpen && (
              <SourcesPanel
                docs={d.docs}
                activeDoc={d.activeDoc}
                uploading={d.uploading}
                onClose={d.toggleSources}
                onUpload={d.triggerUpload}
              />
            )}
          </div>
        </main>

        <SettingsModal
          open={d.settingsOpen}
          responseStyle={d.responseStyle}
          citeSources={d.citeSources}
          onClose={d.closeSettings}
          onStyleChange={d.setResponseStyle}
          onToggleCite={d.toggleCite}
        />

        {voiceActive && (
          <VoiceOverlay
            voiceStatus={d.voiceStatus}
            captionText={d.captionText}
            sources={d.voiceSources}
            muted={d.voiceMuted}
            // Real audio-reactivity for the orb: the employee's own mic
            // while listening, the agent's spoken output while speaking.
            // 'thinking'/'connecting' have no relevant live audio (the
            // orb's own simulated envelope covers those).
            analyser={
              d.voiceStatus === 'listening'
                ? d.voiceInputAnalyser
                : d.voiceStatus === 'speaking'
                  ? d.voiceOutputAnalyser
                  : null
            }
            onToggleMute={d.toggleVoiceMute}
            onClose={d.toggleListen}
            onOpenSource={d.openSource}
          />
        )}
      </div>
    </div>
  );
}
