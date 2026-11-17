/**
 * The signed-in session (SCRUM-40): a bearer token from POST /api/auth/login, kept in this
 * browser until it expires or the user signs out. apiFetch adds it to every API call.
 */

const SESSION_KEY = "stock-research.session";
/** Fired when the API rejects the token (expired or revoked), so the app shows sign-in. */
export const SIGNED_OUT_EVENT = "stock-research:signed-out";

export interface Session {
  token: string;
  username: string;
  /** Epoch milliseconds. */
  expiresAt: number;
}

function isSession(value: unknown): value is Session {
  const item = value as Partial<Session> | null;
  return (
    !!item &&
    typeof item.token === "string" &&
    typeof item.username === "string" &&
    typeof item.expiresAt === "number"
  );
}

export function loadSession(now = Date.now()): Session | null {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(SESSION_KEY) ?? "null");
    if (!isSession(parsed) || parsed.expiresAt <= now) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  try {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    // Storage blocked: the session lasts until the page is closed.
  }
  memory = session;
}

export function clearSession(): void {
  memory = null;
  try {
    window.localStorage.removeItem(SESSION_KEY);
  } catch {
    // Nothing stored.
  }
}

let memory: Session | null = null;

function currentToken(): string | null {
  const session = loadSession() ?? (memory && memory.expiresAt > Date.now() ? memory : null);
  return session?.token ?? null;
}

/** fetch for the API: adds the bearer token, and signs out when the API rejects it. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = currentToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401 && token) {
    clearSession();
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  }
  return response;
}
