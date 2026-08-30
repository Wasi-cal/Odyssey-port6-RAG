'use client';

import { useDocAssist } from '@/hooks/useDocAssist';
import { useAuth } from '@/lib/auth-context';
import { Rail } from './Rail';
import { TopBar } from './TopBar';
import { Sidebar } from './Sidebar';
import { SourcesPanel } from './SourcesPanel';
import { SettingsModal } from './SettingsModal';
import { Composer } from './Composer';
import { HeroEmpty } from './HeroEmpty';
import { DockedThread } from './DockedThread';
import { VoiceScreen } from './VoiceScreen';
import { GradientBackdrop } from './GradientBackdrop';

export function Workspace() {
  const d = useDocAssist();
  const { username, logout } = useAuth();

  const voiceActive = d.voiceStatus !== 'idle';
  const hasMessages = d.messages.length > 0;
  const showHero = !hasMessages;

  const initials = (username || '?').slice(0, 2).toUpperCase();

  // Voice is a real full-screen view now (not an overlay on top of the
  // thread) -- see redesign brief. Everything else (rail/sidebar/sources
  // panel) is unmounted while it's active, same as the reference's
  // dedicated voice screen.
  if (voiceActive) {
    return (
      <VoiceScreen
        voiceStatus={d.voiceStatus}
        captionText={d.captionText}
        sources={d.voiceSources}
        onExit={d.toggleListen}
        onToggleListen={d.toggleListen}
        onOpenSettings={d.openSettings}
        onOpenSource={d.openSource}
      />
    );
  }

  return (
    <div className="relative flex h-screen w-full overflow-hidden text-[#EDF2E6]">
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

      <div className="relative z-[1] flex h-full w-full font-sans">
        <Rail
          sourcesOpen={d.sourcesOpen}
          onNewChat={d.newChat}
          onChatClick={d.goChat}
          onVoiceClick={d.toggleListen}
          onSourcesClick={d.toggleSources}
          onSettingsClick={d.openSettings}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar companyName="Doc Assist" userInitials={initials} onLogout={logout} />

          {d.error && (
            <div className="border-b border-[#4A2318] bg-[#231310] px-7 py-2 text-[13px] text-[#F0A98C]">
              {d.error}
            </div>
          )}

          <div className="relative flex min-h-0 flex-1">
            <Sidebar
              history={d.history}
              activeSessionId={d.activeHistoryTitle}
              onNewChat={d.newChat}
              onSelect={d.selectHistoryItem}
            />

            <div className="relative flex min-w-0 flex-1 flex-col">
              <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
                {showHero ? (
                  <HeroEmpty
                    onToggleListen={d.toggleListen}
                    onPickSuggestion={d.sendMessage}
                    uploadHint={d.uploading ? 'Uploading…' : 'Drop a policy doc here to upload'}
                    onUpload={d.triggerUpload}
                    inputValue={d.inputText}
                    onInputChange={d.setInputText}
                    onSend={d.onComposerSend}
                    activeCategory={d.activeCategory}
                    onCategoryChange={d.setActiveCategory}
                  />
                ) : (
                  <DockedThread messages={d.messages} citeSources={d.citeSources} onOpenSource={d.openSource} />
                )}
              </div>

              {!showHero && (
                <div className="flex-shrink-0 px-8 pb-6 pt-4">
                  <Composer
                    value={d.inputText}
                    onChange={d.setInputText}
                    onSend={d.onComposerSend}
                    onAttach={d.triggerUpload}
                    disabled={d.sending}
                  />
                </div>
              )}
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
        </div>

        <SettingsModal
          open={d.settingsOpen}
          responseStyle={d.responseStyle}
          citeSources={d.citeSources}
          onClose={d.closeSettings}
          onStyleChange={d.setResponseStyle}
          onToggleCite={d.toggleCite}
        />
      </div>
    </div>
  );
}
