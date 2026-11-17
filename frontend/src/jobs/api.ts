import { apiFetch } from "../auth/session";
import type { AnalysisResult, SavedAnalysis } from "./types";

async function errorText(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Not JSON; fall back to the status code.
  }
  return `The API answered ${response.status}.`;
}

export async function listAnalyses(signal?: AbortSignal): Promise<SavedAnalysis[]> {
  const response = await apiFetch("/api/analyses?limit=20", { signal });
  if (!response.ok) throw new Error(await errorText(response));
  return (await response.json()) as SavedAnalysis[];
}

export async function getResult(jobId: string, signal?: AbortSignal): Promise<AnalysisResult> {
  const response = await apiFetch(`/api/jobs/${jobId}/result`, { signal });
  if (!response.ok) throw new Error(await errorText(response));
  return (await response.json()) as AnalysisResult;
}

export function fileUrl(jobId: string, name: string): string {
  return `/api/jobs/${jobId}/files/${encodeURIComponent(name)}`;
}

/** Downloads a saved file. A plain link cannot send the sign-in token, so it is fetched. */
export async function downloadFile(jobId: string, name: string): Promise<void> {
  const response = await apiFetch(fileUrl(jobId, name));
  if (!response.ok) throw new Error(await errorText(response));
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
