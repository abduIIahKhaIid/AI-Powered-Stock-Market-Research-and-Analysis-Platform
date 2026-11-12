/** Saved results of background jobs (SCRUM-34). */

export interface JobFile {
  name: string;
  bytes: number;
  media_type: string;
}

export interface SavedAnalysis {
  id: string;
  kind: string;
  title: string;
  summary: string | null;
  conversation_id: string | null;
  created_at: string;
  finished_at: string | null;
  files: JobFile[];
}

export interface AnalysisResult {
  job: { id: string; kind: string; params: Record<string, unknown>; finished_at: string | null };
  result: unknown;
}

export interface ScanRow {
  last_close?: number;
  last_bar?: string;
  latest?: Record<string, Record<string, number | null>>;
  signals?: string[];
  error?: string;
}

export interface ScanResult {
  symbols: string[];
  indicators: string[];
  period: string;
  rows: Record<string, ScanRow>;
  sources: { source: string; as_of: string | null }[];
}
