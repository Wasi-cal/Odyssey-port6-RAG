'use client';

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

export function Workspace() {
  const d = useDocAssist();
  const { username, logout } = useAuth();

  const voiceActive = d.voiceStatus !== 'idle';
  const hasMessages = d.messages.length > 0;
  const showHero = !hasMessages;

  const initials = (username || '?').slice(0, 2).toUpperCase();

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
          onNewChat={d.newChat}
          onSelect={d.selectHistoryItem}
          onPickShortcut={d.sendMessage}
          onToggleSources={d.toggleSources}
          onOpenSettings={d.openSettings}
          onLogout={logout}
        />

        <main className="relative flex min-w-0 flex-1 flex-col">
          {d.error && (
            <div className="border-b border-[rgba(224,69,90,0.18)] bg-[rgba(224,69,90,0.08)] px-8 py-2 text-[13px] text-[#c23a4d]">
              {d.error}
            </div>
          )}

          <div className="relative flex min-h-0 flex-1">
            <div className="relative flex min-w-0 flex-1 flex-col">
              <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden px-8">
                {showHero ? (
                  <HeroEmpty
                    onPickSuggestion={d.sendMessage}
                    activeCategory={d.activeCategory}
                    onCategoryChange={d.setActiveCategory}
                  />
                ) : (
                  <DockedThread messages={d.messages} citeSources={d.citeSources} onOpenSource={d.openSource} />
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
            onToggleMute={d.toggleVoiceMute}
            onClose={d.toggleListen}
            onOpenSource={d.openSource}
          />
        )}
      </div>
    </div>
  );
}
