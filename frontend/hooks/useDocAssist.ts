'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '@/lib/api';
import { useRealtimeVoice } from './useRealtimeVoice';
import type { Doc, HistoryGroup, Message, ResponseStyle, SessionSummary } from '@/lib/types';

function groupSessions(sessions: SessionSummary[]): HistoryGroup[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayItems: SessionSummary[] = [];
  const earlierItems: SessionSummary[] = [];
  for (const s of sessions) {
    const d = new Date(s.createdAt);
    if (d >= today) todayItems.push(s);
    else earlierItems.push(s);
  }
  const groups: HistoryGroup[] = [];
  if (todayItems.length) groups.push({ group: 'Today', items: todayItems });
  if (earlierItems.length) groups.push({ group: 'Earlier', items: earlierItems });
  return groups;
}

function docMeta(d: api.DocumentInfo): string {
  const date = new Date(d.ingested_at);
  const dateStr = isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
  return `${d.chunk_count} chunk${d.chunk_count === 1 ? '' : 's'}${dateStr ? ` · Updated ${dateStr}` : ''}`;
}

export const SHORTCUT_PROMPTS = [
  { icon: 'search', title: 'Search Policies', q: 'What policies do you have?' },
  { icon: 'leave', title: 'Check Leave Balance', q: 'How many leave days do I have left this year?' },
];

export const PROMPT_CATEGORIES = ['Leave', 'Payroll', 'Travel', 'IT & Security'] as const;

export const CATEGORY_PROMPTS: Record<(typeof PROMPT_CATEGORIES)[number], { title: string; q: string }[]> = {
  Leave: [
    { title: "What's our parental leave policy?", q: "What's our parental leave policy?" },
    { title: 'How many PTO days do I get after 2 years?', q: 'How many PTO days do I get after 2 years?' },
  ],
  Payroll: [
    { title: 'How do I submit an expense report?', q: 'How do I submit an expense report?' },
    { title: 'What is the referral bonus payout?', q: 'What is the referral bonus payout?' },
  ],
  Travel: [
    { title: "What's the hotel reimbursement cap?", q: "What's the hotel reimbursement cap for business travel?" },
    { title: 'What class of air travel am I entitled to?', q: 'What class of air travel am I entitled to for business trips?' },
  ],
  'IT & Security': [
    { title: 'How do I request new hire equipment?', q: 'How do I request new hire equipment?' },
    { title: 'Who do I report a phishing attempt to?', q: 'Who do I report a phishing attempt to?' },
  ],
};

/**
 * All Doc Assist workspace state and behavior, backed by the real FastAPI
 * backend (see backend/api.py) -- /sessions + /ask for chat, /library +
 * /ingest for documents. Voice is a real OpenAI Realtime API WebRTC
 * connection (see useRealtimeVoice) -- no more browser
 * SpeechRecognition/speechSynthesis placeholder.
 */
export function useDocAssist() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [inputText, setInputText] = useState('');
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activeDoc, setActiveDoc] = useState<string | null>(null);
  const [responseStyle, setResponseStyleState] = useState<ResponseStyle>('balanced');
  const [citeSources, setCiteSources] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<(typeof PROMPT_CATEGORIES)[number]>('Leave');

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const refreshLibrary = useCallback(() => {
    api
      .getLibrary()
      .then((rows) => setDocs(rows.map((d) => ({ name: d.name, meta: docMeta(d) }))))
      .catch(() => {});
  }, []);

  const refreshSessions = useCallback(() => {
    api
      .listSessions()
      .then((rows) => setSessions(rows.map((s) => ({ id: s.id, title: s.title, createdAt: s.created_at }))))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshLibrary();
    refreshSessions();
  }, [refreshLibrary, refreshSessions]);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId;
    const s = await api.createSession();
    setSessionId(s.id);
    setSessions((prev) => [{ id: s.id, title: s.title, createdAt: s.created_at }, ...prev]);
    return s.id;
  }, [sessionId]);

  const askBackend = useCallback(
    async (question: string): Promise<Message> => {
      const sid = await ensureSession();
      const res = await api.ask(question, sid);
      if (res.title) {
        setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, title: res.title } : s)));
      }
      return { role: 'assistant', text: res.answer, sources: res.sources };
    },
    [ensureSession],
  );

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || sending) return;
      setError(null);
      setMessages((m) => [...m, { role: 'user', text }]);
      setInputText('');
      setSending(true);
      try {
        const reply = await askBackend(text);
        setMessages((m) => [...m, reply]);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to reach Doc Assist.');
        setMessages((m) => m.slice(0, -1));
      } finally {
        setSending(false);
      }
    },
    [askBackend, sending],
  );

  const onComposerSend = useCallback(() => {
    const text = inputText.trim();
    if (!text) return;
    sendMessage(text);
  }, [inputText, sendMessage]);

  // Voice exchanges land here the moment /voice/ask resolves inside the
  // realtime session's search_policies tool call -- same tagging
  // (viaVoice: true) the old commitVoiceExchange used, just driven by a
  // real WebRTC session instead of a single-shot SpeechRecognition call.
  const onVoiceExchangeComplete = useCallback((question: string, reply: Message) => {
    setMessages((m) => [...m, { role: 'user', text: question, viaVoice: true }, { ...reply, viaVoice: true }]);
  }, []);

  const voice = useRealtimeVoice({ getSessionId: ensureSession, onExchangeComplete: onVoiceExchangeComplete });

  useEffect(() => {
    if (voice.error) setError(voice.error);
  }, [voice.error]);

  const newChat = useCallback(() => {
    voice.disconnect();
    setMessages([]);
    setSessionId(null);
    setInputText('');
    setSourcesOpen(false);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectHistoryItem = useCallback(async (item: SessionSummary) => {
    setSourcesOpen(false);
    setSessionId(item.id);
    try {
      const msgs = await api.getSessionMessages(item.id);
      setMessages(
        msgs.map((m) => ({
          role: m.role === 'user' ? 'user' : 'assistant',
          text: m.content,
          sources: m.meta?.sources,
        })),
      );
    } catch {
      setMessages([]);
    }
  }, []);

  const openSource = useCallback((doc?: string) => {
    if (!doc) return;
    setSourcesOpen(true);
    setActiveDoc(doc);
  }, []);

  const toggleSources = useCallback(() => setSourcesOpen((v) => !v), []);
  const goChat = useCallback(() => setSourcesOpen(false), []);

  // Single entry point for every mic/voice affordance. Idle -> opens a
  // real-time WebRTC connection to OpenAI; anything else -> tears it down.
  const toggleListen = useCallback(() => {
    if (voice.status === 'idle') {
      voice.connect();
    } else {
      voice.disconnect();
    }
  }, [voice]);

  const uploadFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (!list.length) return;
      setUploading(true);
      setError(null);
      try {
        await api.uploadDocuments(list);
        refreshLibrary();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Upload failed.');
      } finally {
        setUploading(false);
      }
    },
    [refreshLibrary],
  );

  const triggerUpload = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  return {
    messages,
    inputText,
    setInputText,
    sourcesOpen,
    settingsOpen,
    activeDoc,
    activeHistoryTitle: sessionId,
    voiceStatus: voice.status,
    captionText: voice.captionText,
    voiceSources: voice.sources,
    voiceMuted: voice.muted,
    toggleVoiceMute: voice.toggleMute,
    responseStyle,
    citeSources,
    uploading,
    docs,
    history: groupSessions(sessions),
    sessions,
    sending,
    error,
    fileInputRef,
    activeCategory,
    setActiveCategory,
    sendMessage,
    onComposerSend,
    newChat,
    selectHistoryItem,
    openSource,
    toggleSources,
    goChat,
    toggleListen,
    triggerUpload,
    uploadFiles,
    openSettings: () => setSettingsOpen(true),
    closeSettings: () => setSettingsOpen(false),
    setResponseStyle: (v: ResponseStyle) => setResponseStyleState(v),
    toggleCite: () => setCiteSources((v) => !v),
  };
}
