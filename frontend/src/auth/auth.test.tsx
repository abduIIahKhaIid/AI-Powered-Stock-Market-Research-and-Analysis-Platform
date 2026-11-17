import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AuthGate from "../AuthGate";
import { loadConversations, saveConversations, setStorageScope } from "../chat/storage";
import SignIn from "../components/SignIn";
import { apiFetch, loadSession, SIGNED_OUT_EVENT, saveSession } from "./session";

const HEALTH = { status: "ok", services: { api: "ok" } };

function session(username = "alice", token = "tok-1") {
  return { token, username, expiresAt: Date.now() + 3_600_000 };
}

/** A fake API: auth config, /auth/me for a valid token, login, health and analyses. */
function mockApi(options: { enabled?: boolean; validToken?: string } = {}) {
  const { enabled = true, validToken = "tok-1" } = options;
  const calls: { url: string; auth: string | null }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const auth = new Headers(init?.headers).get("Authorization");
    calls.push({ url, auth });
    if (url.endsWith("/api/auth/config")) {
      return Response.json({ enabled, signup: true, invite_required: false });
    }
    if (url.endsWith("/api/auth/me")) {
      return auth === `Bearer ${validToken}`
        ? Response.json({ username: "alice", auth_enabled: true })
        : Response.json({ detail: "Sign in." }, { status: 401 });
    }
    if (url.endsWith("/api/auth/login")) {
      const body = JSON.parse(String(init?.body)) as { password: string };
      return body.password === "right password"
        ? Response.json({ access_token: validToken, expires_in: 3600, username: "alice" })
        : Response.json({ detail: "Wrong username or password." }, { status: 401 });
    }
    if (url.endsWith("/api/health")) return Response.json(HEALTH);
    if (url.includes("/api/analyses")) return Response.json([]);
    return Response.json({}, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

beforeEach(() => {
  window.localStorage.clear();
  setStorageScope(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("sends the bearer token and signs out when the API rejects it", async () => {
    saveSession(session("alice", "old"));
    const calls = mockApi({ validToken: "new" });
    const signedOut = vi.fn();
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);

    const response = await apiFetch("/api/auth/me");

    expect(response.status).toBe(401);
    expect(calls[0].auth).toBe("Bearer old");
    expect(loadSession()).toBeNull();
    expect(signedOut).toHaveBeenCalledTimes(1);
    window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
  });

  it("ignores an expired session", () => {
    saveSession({ token: "t", username: "a", expiresAt: Date.now() - 1 });
    expect(loadSession()).toBeNull();
  });
});

describe("Sign-in screen", () => {
  it("shows the server's message when sign-in fails, and switches to account creation", async () => {
    const submitSignIn = vi.fn().mockRejectedValue(new Error("Wrong username or password."));
    render(
      <SignIn
        config={{ enabled: true, signup: true, invite_required: true }}
        onSignedIn={vi.fn()}
        submitSignIn={submitSignIn}
      />,
    );
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
    expect(submitSignIn).toHaveBeenCalledWith("alice", "nope");

    fireEvent.click(screen.getByRole("button", { name: "Create an account" }));
    expect(screen.getByRole("heading", { name: "Create your account" })).toBeInTheDocument();
    expect(screen.getByLabelText("Invite code")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("AuthGate", () => {
  it("asks to sign in, then opens the app for that user", async () => {
    mockApi();
    render(<AuthGate />);

    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "right password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    expect(loadSession()?.token).toBe("tok-1");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(loadSession()).toBeNull();
  });

  it("goes straight to the app with a valid saved session", async () => {
    saveSession(session());
    mockApi();
    render(<AuthGate />);
    expect(await screen.findByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("returns to sign-in with a notice when the session ends", async () => {
    saveSession(session());
    mockApi();
    render(<AuthGate />);
    await screen.findByRole("button", { name: "Sign out" });

    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
    expect(await screen.findByText(/Your session has ended/)).toBeInTheDocument();
  });

  it("opens the app without sign-in when the server has it turned off", async () => {
    mockApi({ enabled: false });
    render(<AuthGate />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Ask about any NASDAQ stock/ }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
  });
});

describe("Conversation storage per user", () => {
  it("keeps users apart and gives the first user the conversations from before sign-in", () => {
    const old = {
      id: "a",
      serverId: null,
      title: "Old chat",
      messages: [],
      createdAt: 1,
      updatedAt: 1,
    };
    saveConversations([old]);

    setStorageScope("Alice");
    expect(loadConversations().map((c) => c.title)).toEqual(["Old chat"]);

    setStorageScope("bob");
    expect(loadConversations()).toEqual([]);
    saveConversations([{ ...old, id: "b", title: "Bob's chat" }]);

    setStorageScope("alice");
    expect(loadConversations().map((c) => c.title)).toEqual(["Old chat"]);
  });
});
