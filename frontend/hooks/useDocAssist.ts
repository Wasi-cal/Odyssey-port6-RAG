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

// -- Client-side cache ------------------------------------------------------
//
// Bug fix: previously nothing about the conversation/session list survived a
// refresh except a synchronous re-fetch (spinner, then a flash of empty
// state, then content) -- there was no local cache at all. This is a small,
// dependency-free localStorage cache (matches this codebase's existing
// convention of a lightweight custom hook over pulling in a library like
// React Query, which package.json confirms isn't used anywhere else here):
// the active session id, its messages, and the session list are mirrored
// into localStorage on every change, and read back synchronously (via
// useState's lazy initializer, below) on mount -- so a refresh shows the
// exact same conversation and sidebar instantly, with the real backend
// fetch still happening in the background to reconcile/confirm it.
const CACHE_KEY = 'docAssist:cache:v1';

interface CachedState {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  messagesBySession: Record<string, Message[]>;
}

const EMPTY_CACHE: CachedState = { sessions: [], activeSessionId: null, messagesBySession: {} };

function loadCache(): CachedState {
  if (typeof window === 'undefined') return EMPTY_CACHE;
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return EMPTY_CACHE;
    const parsed = JSON.parse(raw);
    return {
      sessions: Array.isArray(parsed.sessions) ? parsed.sessions : [],
      activeSessionId: typeof parsed.activeSessionId === 'string' ? parsed.activeSessionId : null,
      messagesBySession:
        parsed.messagesBySession && typeof parsed.messagesBySession === 'object' ? parsed.messagesBySession : {},
    };
  } catch {
    return EMPTY_CACHE;
  }
}

// Caps how many past sessions' messages are kept in localStorage -- an
// unbounded cache would otherwise grow forever as new sessions pile up.
// Keeps the most recently touched sessions (by their position in `sessions`,
// which the backend already returns newest-first) plus whichever session is
// currently active.
const MAX_CACHED_SESSIONS = 50;

function saveCache(state: CachedState) {
  if (typeof window === 'undefined') return;
  try {
    const keep = new Set(state.sessions.slice(0, MAX_CACHED_SESSIONS).map((s) => s.id));
    if (state.activeSessionId) keep.add(state.activeSessionId);
    const trimmedMessages: Record<string, Message[]> = {};
    for (const [id, msgs] of Object.entries(state.messagesBySession)) {
      if (keep.has(id)) trimmedMessages[id] = msgs;
    }
    window.localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ ...state, messagesBySession: trimmedMessages }),
    );
  } catch {
    // Storage full/unavailable -- caching is a convenience, never fatal.
  }
}

function docMeta(d: api.DocumentInfo): string {
  const date = new Date(d.ingested_at);
  const dateStr = isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
  return `${d.chunk_count} chunk${d.chunk_count === 1 ? '' : 's'}${dateStr ? ` · Updated ${dateStr}` : ''}`;
}

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
  // Lazy initializers -- read once, synchronously, on mount, so the very
  // first render already shows the cached conversation/session list instead
  // of an empty state that then pops in once the network round-trip below
  // resolves.
  const [messages, setMessages] = useState<Message[]>(() => {
    const cache = loadCache();
    return (cache.activeSessionId && cache.messagesBySession[cache.activeSessionId]) || [];
  });
  const [sessionId, setSessionId] = useState<string | null>(() => loadCache().activeSessionId);
  const [inputText, setInputText] = useState('');
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activeDoc, setActiveDoc] = useState<string | null>(null);
  const [responseStyle, setResponseStyleState] = useState<ResponseStyle>('balanced');
  const [citeSources, setCiteSources] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>(() => loadCache().sessions);
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
      .then((rows) => {
        const mapped = rows.map((s) => ({ id: s.id, title: s.title, createdAt: s.created_at }));
        setSessions(mapped);
        saveCache({ ...loadCache(), sessions: mapped });
      })
      .catch(() => {});
  }, []);

  // Keeps localStorage's copy of the active conversation in sync with
  // in-memory state on every change (new question, new answer, switching
  // sessions, starting a new chat) -- this is the one place that writes
  // messages/activeSessionId to the cache, so every code path that mutates
  // them (sendMessage, selectHistoryItem, newChat, voice exchanges) is
  // covered without needing its own explicit cache-write call.
  useEffect(() => {
    const cache = loadCache();
    const messagesBySession = { ...cache.messagesBySession };
    if (sessionId) messagesBySession[sessionId] = messages;
    saveCache({ sessions: cache.sessions, activeSessionId: sessionId, messagesBySession });
  }, [messages, sessionId]);

  // On mount: the lazy initializers above already restored the cached
  // session list + active conversation instantly (no spinner, no flash of
  // empty state). These calls confirm both against the real backend in the
  // background and reconcile -- refreshLibrary/refreshSessions always
  // did this; the getSessionMessages call is new, and only runs when a
  // cached session id exists. If that session turns out to be gone (e.g.
  // deleted, or the cache is stale/from another account), fall back to a
  // clean empty state instead of leaving a broken cached conversation on
  // screen forever.
  useEffect(() => {
    refreshLibrary();
    refreshSessions();
    const cachedSessionId = loadCache().activeSessionId;
    if (cachedSessionId) {
      api
        .getSessionMessages(cachedSessionId)
        .then((msgs) => {
          setMessages(
            msgs.map((m) => ({
              role: m.role === 'user' ? 'user' : 'assistant',
              text: m.content,
              sources: m.meta?.sources,
            })),
          );
        })
        .catch(() => {
          setMessages([]);
          sessionIdRef.current = null;
          setSessionId(null);
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshLibrary, refreshSessions]);

  // Bug fix (#7): every voice exchange was being persisted as its own new
  // conversation instead of continuing the current one. Root cause: this
  // used to be `useCallback(..., [sessionId])`, so its identity (and the
  // `sessionId` value closed over inside it) was fixed at whatever render
  // was current when useRealtimeVoice's connect() captured it as
  // `getSessionId`. That one frozen closure is what every subsequent
  // search_policies tool call during that same voice overlay session
  // re-invokes -- it always saw the `sessionId` that was in scope back at
  // connect()-time (frequently still null, since createSession() resolves
  // asynchronously after the closure was already captured), so it created
  // a brand new chat session on every single voice query instead of
  // reusing the one just created.
  //
  // Fix: sessionIdRef always holds the latest session id (updated both
  // synchronously the instant a session is created below, and mirrored by
  // the effect below for every other path that changes sessionId --
  // newChat, selectHistoryItem). ensureSession itself now has a stable,
  // dependency-free identity (`useCallback(..., [])`) that always reads
  // sessionIdRef.current fresh on every call, so the *same* function
  // object handed to useRealtimeVoice as getSessionId keeps returning
  // whichever session is actually current, for as many voice (or text)
  // exchanges as happen -- one conversation per overlay open (or
  // continuing whatever conversation was already active), not one per
  // query. pendingSessionRef additionally guards against two concurrent
  // callers (e.g. a voice query firing right as ensureSession's own
  // createSession() call is still in flight) each minting their own
  // session before either one has set sessionIdRef.
  const sessionIdRef = useRef<string | null>(sessionId);
  const pendingSessionRef = useRef<Promise<string> | null>(null);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionIdRef.current) return sessionIdRef.current;
    if (pendingSessionRef.current) return pendingSessionRef.current;
    const pending = (async () => {
      const s = await api.createSession();
      sessionIdRef.current = s.id;
      setSessionId(s.id);
      setSessions((prev) => [{ id: s.id, title: s.title, createdAt: s.created_at }, ...prev]);
      return s.id;
    })();
    pendingSessionRef.current = pending;
    try {
      return await pending;
    } finally {
      pendingSessionRef.current = null;
    }
  }, []);

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
        console.error('[chat] sendMessage failed:', err);
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
    // Logged, not surfaced as a UI banner -- voice errors were confirmed
    // repeatedly noisy/non-actionable (benign server-side messages,
    // races that self-resolve, etc.), console is where they're useful.
    if (voice.error) console.error('[voice] error:', voice.error);
  }, [voice.error]);

  const newChat = useCallback(() => {
    voice.disconnect();
    setMessages([]);
    sessionIdRef.current = null;
    setSessionId(null);
    setInputText('');
    setSourcesOpen(false);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectHistoryItem = useCallback(async (item: SessionSummary) => {
    setSourcesOpen(false);
    sessionIdRef.current = item.id;
    setSessionId(item.id);
    // Instant restore from cache (if this session's messages were cached
    // earlier), then confirm/reconcile against the real backend below --
    // avoids the spinner-then-refetch flash for a conversation that's
    // already been seen this session.
    const cached = loadCache().messagesBySession[item.id];
    setMessages(cached || []);
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
      if (!cached) setMessages([]);
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
        console.error('[documents] upload failed:', err);
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
    voiceInputAnalyser: voice.inputAnalyser,
    voiceOutputAnalyser: voice.outputAnalyser,
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
