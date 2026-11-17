/** Sign-in endpoints (SCRUM-40): /api/auth/config, /register, /login and /me. */
import { apiFetch, type Session } from "./session";

export interface AuthConfig {
  enabled: boolean;
  signup: boolean;
  invite_required: boolean;
}

export class AuthError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return "Check the username and password and try again.";
  } catch {
    // Not JSON.
  }
  if (response.status === 429) return "Too many attempts. Wait a minute and try again.";
  return `The server answered with HTTP ${response.status}.`;
}

export async function getAuthConfig(): Promise<AuthConfig> {
  const response = await fetch("/api/auth/config");
  if (!response.ok) throw new AuthError(response.status, await detail(response));
  return (await response.json()) as AuthConfig;
}

interface TokenResponse {
  access_token: string;
  expires_in: number;
  username: string;
}

async function tokenRequest(path: string, body: Record<string, string>): Promise<Session> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new AuthError(response.status, await detail(response));
  const token = (await response.json()) as TokenResponse;
  return {
    token: token.access_token,
    username: token.username,
    expiresAt: Date.now() + token.expires_in * 1000,
  };
}

export function signIn(username: string, password: string): Promise<Session> {
  return tokenRequest("/api/auth/login", { username, password });
}

export function createAccount(
  username: string,
  password: string,
  inviteCode?: string,
): Promise<Session> {
  const body: Record<string, string> = { username, password };
  if (inviteCode) body.invite_code = inviteCode;
  return tokenRequest("/api/auth/register", body);
}

/** The signed-in user's name, or null when the token is no longer accepted. */
export async function whoAmI(): Promise<string | null> {
  const response = await apiFetch("/api/auth/me");
  if (response.status === 401) return null;
  if (!response.ok) throw new AuthError(response.status, await detail(response));
  return ((await response.json()) as { username: string }).username;
}
