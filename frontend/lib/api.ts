// Thin fetch wrapper around the FastAPI backend (see backend/api.py). Every
// call goes through Next.js's /api/* rewrite (next.config.mjs) to the
// backend origin, so there's no CORS to configure. The JWT is kept in
// localStorage (read here on every call) and mirrored into a cookie on
// login so plain <a href> document links (GET /documents/{filename}) still
// authenticate via the backend's cookie fallback.

const TOKEN_KEY = 'doc_assist_jwt';
// Separate storage key -- the backend issues a distinct admin JWT
// (auth.create_admin_token) from a distinct login endpoint (POST
// /admin/login), never the regular user token, and get_current_admin
// never accepts a cookie fallback (see api.py's docstring) so this one
// only ever needs to travel as an Authorization header, not a cookie.
const ADMIN_TOKEN_KEY = 'doc_assist_admin_jwt';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === 'undefined') return;
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
    document.cookie = `doc_assist_jwt=${token}; path=/; max-age=2592000; SameSite=Lax`;
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
    document.cookie = 'doc_assist_jwt=; path=/; max-age=0';
  }
}

export function getAdminToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ADMIN_TOKEN_KEY);
}

export function setAdminToken(token: string | null) {
  if (typeof window === 'undefined') return;
  if (token) window.localStorage.setItem(ADMIN_TOKEN_KEY, token);
  else window.localStorage.removeItem(ADMIN_TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function doFetch<T>(path: string, token: string | null, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // no JSON body
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function request<T>(path: string, init?: RequestInit): Promise<T> {
  return doFetch<T>(path, getToken(), init);
}

function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  return doFetch<T>(path, getAdminToken(), init);
}

// --- Auth -------------------------------------------------------------

export interface TokenResponse {
  access_token: string;
  token_type: string;
  username: string;
}

export function login(username: string, password: string) {
  return request<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function register(username: string, password: string) {
  return request<TokenResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function whoami() {
  return request<{ username: string }>('/auth/me');
}

// --- Sessions / chat ----------------------------------------------------

export interface SessionInfo {
  id: string;
  title: string | null;
  created_at: string;
}

export interface MessageInfo {
  role: string;
  content: string;
  meta: { sources?: SourceApi[]; num_chunks?: number; latency_ms?: number } | null;
}

export interface SourceApi {
  label: string;
  filename: string;
  page: number | null;
}

export interface AskResponse {
  answer: string;
  sources: SourceApi[];
  num_chunks: number;
  latency_ms: number;
  title: string | null;
}

export function listSessions() {
  return request<SessionInfo[]>('/sessions');
}

export function createSession() {
  return request<SessionInfo>('/sessions', { method: 'POST' });
}

export function getSessionMessages(sessionId: string) {
  return request<MessageInfo[]>(`/sessions/${sessionId}/messages`);
}

// --- Voice (realtime, provider-agnostic) ---------------------------------

/** OpenAI's connection details -- see assistant/voice/openai_provider.py. */
export interface OpenAIVoiceConnection {
  model: string;
  voice: string;
}

/** Deepgram's connection details -- see assistant/voice/deepgram_provider.py. */
export interface DeepgramVoiceConnection {
  websocket_url: string;
  settings: Record<string, unknown>; // the Settings message to send verbatim once the socket opens
}

export interface VoiceSessionResponse {
  provider: 'openai' | 'deepgram';
  credential: string; // ephemeral, session-scoped -- never the underlying provider API key
  expires_at: number;
  connection: OpenAIVoiceConnection | DeepgramVoiceConnection | Record<string, unknown>;
}

/**
 * Mints a short-lived, session-scoped credential for whichever
 * RealtimeVoiceProvider config_store's voice/provider selects -- see
 * backend/api.py's POST /voice/session and assistant/voice/base.py.
 */
export function createVoiceSession() {
  return request<VoiceSessionResponse>('/voice/session', { method: 'POST' });
}

export interface VoiceAskResponse {
  answer: string;
  sources: SourceApi[];
  num_chunks: number;
  latency_ms: number;
}

/** Short, spoken-style answer -- what the realtime model's search_policies tool call hits. */
export function voiceAsk(question: string, sessionId: string) {
  return request<VoiceAskResponse>('/voice/ask', {
    method: 'POST',
    body: JSON.stringify({ question, session_id: sessionId }),
  });
}

export function ask(question: string, sessionId: string) {
  return request<AskResponse>('/ask', {
    method: 'POST',
    body: JSON.stringify({ question, session_id: sessionId }),
  });
}

// --- Library / uploads ---------------------------------------------------

export interface DocumentInfo {
  name: string;
  chunk_count: number;
  ingested_at: string;
}

export function getLibrary() {
  return request<DocumentInfo[]>('/library');
}

export interface UploadResponse {
  queued: string[];
  skipped: string[];
  renamed: Record<string, string>;
}

export function uploadDocuments(files: File[]) {
  const form = new FormData();
  for (const f of files) form.append('files', f);
  return request<UploadResponse>('/ingest', { method: 'POST', body: form });
}

// GET /documents/{filename} (backend/routers/documents.py) is a regular,
// non-admin-gated endpoint (get_current_user, same as /library) -- it
// already serves any logged-in user's own request for a document's raw
// bytes, just with `Content-Disposition: inline` (meant for the existing
// "open in a new tab to view" links). For a real download button (bug 6),
// fetching the bytes ourselves with the Authorization header (rather than
// a plain <a href>, which can't attach one) and handing them to the
// browser as a blob works regardless of that inline disposition -- the
// `download` attribute on the temporary anchor below is what actually
// forces a save-as instead of a navigation.
export async function downloadDocument(filename: string): Promise<void> {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(`/api/documents/${encodeURIComponent(filename)}`, { headers });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

// --- Admin ----------------------------------------------------------------
// Every function here uses adminRequest (the separate admin JWT), never the
// regular user token -- mirrors backend/api.py's get_current_admin split.

export interface AdminTokenResponse {
  access_token: string;
  token_type: string;
}

export function adminLogin(admin_password: string) {
  return request<AdminTokenResponse>('/admin/login', {
    method: 'POST',
    body: JSON.stringify({ admin_password }),
  });
}

export interface AdminPendingDocumentInfo {
  id: string;
  filename: string;
  uploaded_by: string;
  uploaded_at: string;
}

export function listPendingDocumentsAdmin() {
  return adminRequest<AdminPendingDocumentInfo[]>('/admin/pending-documents');
}

export function approvePendingDocument(id: string) {
  return adminRequest<{ approved: string; chunk_count: number }>(
    `/admin/pending-documents/${id}/approve`,
    { method: 'POST' },
  );
}

export function rejectPendingDocument(id: string) {
  return adminRequest<{ rejected: string }>(`/admin/pending-documents/${id}/reject`, {
    method: 'POST',
  });
}

export function listDocumentsAdmin() {
  return adminRequest<DocumentInfo[]>('/admin/documents');
}

export interface AdminUploadResponse {
  ingested: string[];
  skipped: string[];
  renamed: Record<string, string>;
}

export function uploadDocumentsAdmin(files: File[]) {
  const form = new FormData();
  for (const f of files) form.append('files', f);
  return adminRequest<AdminUploadResponse>('/admin/documents', { method: 'POST', body: form });
}

export function deleteDocumentAdmin(filename: string) {
  return adminRequest<{ deleted: string }>(`/admin/documents/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  });
}

export interface MonitoringResponse {
  pending_approvals: number;
  embeddings_present: number;
  tokens_consumed: number;
  cost_usd: number;
  average_token_usage: number;
}

export function getMonitoring() {
  return adminRequest<MonitoringResponse>('/admin/monitoring');
}

export interface AuditLogEntry {
  action: string;
  filename: string;
  performed_by: string;
  performed_at: string;
}

export function getAuditLog() {
  return adminRequest<AuditLogEntry[]>('/admin/audit-log');
}

export function adminResetPassword(username: string, new_password: string) {
  return adminRequest<{ reset: string }>('/admin/reset-password', {
    method: 'POST',
    body: JSON.stringify({ username, new_password }),
  });
}

export function adminChangePassword(new_admin_password: string) {
  return adminRequest<{ changed: boolean }>('/admin/change-password', {
    method: 'POST',
    body: JSON.stringify({ new_admin_password }),
  });
}
