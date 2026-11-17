/** Sign in, or create an account (SCRUM-40). */
import { type FormEvent, useId, useState } from "react";
import { type AuthConfig, createAccount, signIn } from "../auth/api";
import type { Session } from "../auth/session";

interface Props {
  config: AuthConfig;
  onSignedIn: (session: Session) => void;
  /** Shown above the form, e.g. after a session expired. */
  notice?: string | null;
  /** Injected in tests. */
  submitSignIn?: typeof signIn;
  submitCreate?: typeof createAccount;
}

export default function SignIn({
  config,
  onSignedIn,
  notice,
  submitSignIn = signIn,
  submitCreate = createAccount,
}: Props) {
  const [creating, setCreating] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const errorId = useId();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = creating
        ? await submitCreate(username.trim(), password, invite.trim() || undefined)
        : await submitSignIn(username.trim(), password);
      onSignedIn(session);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const action = creating ? "Create account" : "Sign in";
  return (
    <main className="signin">
      <form
        className="signin-card"
        onSubmit={submit}
        aria-describedby={error ? errorId : undefined}
      >
        <span className="brand">
          <span className="brand-mark" aria-hidden="true">
            ▲
          </span>
          Stock Research
        </span>
        <h1 className="signin-title">{creating ? "Create your account" : "Sign in"}</h1>
        {notice && !error && <p className="signin-notice">{notice}</p>}

        <label className="field">
          <span>Username</span>
          <input
            name="username"
            autoComplete="username"
            required
            minLength={creating ? 3 : 1}
            maxLength={32}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            name="password"
            type="password"
            autoComplete={creating ? "new-password" : "current-password"}
            required
            minLength={creating ? 8 : 1}
            maxLength={128}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {creating && <small className="muted">At least 8 characters.</small>}
        </label>
        {creating && config.invite_required && (
          <label className="field">
            <span>Invite code</span>
            <input
              name="invite"
              autoComplete="off"
              required
              value={invite}
              onChange={(event) => setInvite(event.target.value)}
            />
          </label>
        )}

        {error && (
          <p id={errorId} className="signin-error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="send signin-submit" disabled={busy}>
          {busy ? `${action}…` : action}
        </button>

        {config.signup && (
          <p className="signin-switch">
            {creating ? "Already have an account?" : "New here?"}{" "}
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setCreating(!creating);
                setError(null);
              }}
            >
              {creating ? "Sign in" : "Create an account"}
            </button>
          </p>
        )}
      </form>
    </main>
  );
}
