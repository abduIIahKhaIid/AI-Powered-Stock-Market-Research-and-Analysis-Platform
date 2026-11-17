/**
 * Shows the sign-in screen until the user is signed in, then the app (SCRUM-40). When the
 * server has sign-in turned off, the app opens directly.
 */
import { useEffect, useState } from "react";
import App from "./App";
import { type AuthConfig, getAuthConfig, whoAmI } from "./auth/api";
import {
  clearSession,
  loadSession,
  SIGNED_OUT_EVENT,
  type Session,
  saveSession,
} from "./auth/session";
import { setStorageScope } from "./chat/storage";
import SignIn from "./components/SignIn";

type State =
  | { kind: "checking" }
  | { kind: "unreachable"; message: string }
  | { kind: "open" }
  | { kind: "signed-out"; config: AuthConfig; notice: string | null }
  | { kind: "signed-in"; config: AuthConfig; username: string };

export default function AuthGate() {
  const [state, setState] = useState<State>({ kind: "checking" });

  // Bumped by "Try again" to run the check once more.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const config = await getAuthConfig();
        if (!config.enabled) {
          setStorageScope(null);
          if (!cancelled) setState({ kind: "open" });
          return;
        }
        const username = loadSession() ? await whoAmI() : null;
        if (cancelled) return;
        if (username) {
          setStorageScope(username);
          setState({ kind: "signed-in", config, username });
        } else {
          clearSession();
          setState({ kind: "signed-out", config, notice: null });
        }
      } catch (problem) {
        if (cancelled) return;
        setState({
          kind: "unreachable",
          message: problem instanceof Error ? problem.message : "The API could not be reached.",
        });
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  useEffect(() => {
    const expired = () =>
      setState((current) =>
        current.kind === "signed-in"
          ? {
              kind: "signed-out",
              config: current.config,
              notice: "Your session has ended. Sign in again to continue.",
            }
          : current,
      );
    window.addEventListener(SIGNED_OUT_EVENT, expired);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, expired);
  }, []);

  if (state.kind === "checking") {
    return (
      <p className="signin-status muted" role="status">
        Loading…
      </p>
    );
  }
  if (state.kind === "unreachable") {
    return (
      <div className="signin-status" role="alert">
        <p>The API could not be reached: {state.message}</p>
        <button
          type="button"
          className="new-chat"
          onClick={() => {
            setState({ kind: "checking" });
            setAttempt((count) => count + 1);
          }}
        >
          Try again
        </button>
      </div>
    );
  }
  if (state.kind === "open") return <App />;
  if (state.kind === "signed-out") {
    return (
      <SignIn
        config={state.config}
        notice={state.notice}
        onSignedIn={(session: Session) => {
          saveSession(session);
          setStorageScope(session.username);
          setState({ kind: "signed-in", config: state.config, username: session.username });
        }}
      />
    );
  }
  return (
    <App
      key={state.username}
      user={{
        username: state.username,
        onSignOut: () => {
          clearSession();
          setState({ kind: "signed-out", config: state.config, notice: null });
        },
      }}
    />
  );
}
