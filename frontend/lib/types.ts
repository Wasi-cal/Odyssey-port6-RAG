export type Role = 'user' | 'assistant';

export interface SourceInfo {
  label: string;
  filename: string;
  page: number | null;
}

export interface Message {
  role: Role;
  text: string;
  sources?: SourceInfo[];
  viaVoice?: boolean;
}

export interface Doc {
  name: string;
  meta: string;
}

export interface SessionSummary {
  id: string;
  title: string | null;
  createdAt: string;
}

export interface HistoryGroup {
  group: string;
  items: SessionSummary[];
}

export type VoiceStatus = 'idle' | 'connecting' | 'listening' | 'speaking';
export type ResponseStyle = 'concise' | 'balanced' | 'detailed';
