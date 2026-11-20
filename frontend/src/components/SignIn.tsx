/** Sign in, or create an account (SCRUM-40). */
import { LockIcon, TrendingUpIcon } from "lucide-react";
import { type FormEvent, type ReactNode, useId, useState } from "react";
import { type AuthConfig, createAccount, signIn } from "../auth/api";
import type { Session } from "../auth/session";
import { Button } from "./ui/button";

interface Props {
  config: AuthConfig;
  onSignedIn: (session: Session) => void;
  /** Shown above the form, e.g. after a session expired. */
  notice?: string | null;
  /** Injected in tests. */
  submitSignIn?: typeof signIn;
  submitCreate?: typeof createAccount;
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="space-y-1">
      <label className="block space-y-1.5">
        <span className="text-sm font-medium">{label}</span>
        {children}
      </label>
      {hint && <small className="block text-xs text-muted-foreground">{hint}</small>}
    </div>
  );
}

const INPUT =
  "h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none transition-shadow focus:border-primary/50 focus:ring-4 focus:ring-primary/10";

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
    <main className="relative grid min-h-full place-items-center overflow-hidden bg-background p-4">
      <div
        className="pointer-events-none absolute -top-40 left-1/2 size-[36rem] -translate-x-1/2 rounded-full bg-gradient-to-br from-indigo-500/20 via-violet-500/10 to-emerald-500/20 blur-3xl"
        aria-hidden="true"
      />
      <form
        className="relative w-full max-w-sm animate-fade-up space-y-4 rounded-2xl border border-border bg-card p-7 shadow-xl"
        onSubmit={submit}
        aria-describedby={error ? errorId : undefined}
      >
        <span className="flex items-center gap-2 text-[15px] font-semibold">
          <span
            className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-emerald-500 text-white"
            aria-hidden="true"
          >
            <TrendingUpIcon className="size-4" strokeWidth={2.5} />
          </span>
          Stock Research
        </span>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {creating ? "Create your account" : "Sign in"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            NASDAQ research with sources on every answer.
          </p>
        </div>
        {notice && !error && (
          <p className="rounded-lg bg-warning/10 px-3 py-2 text-sm text-amber-800 dark:text-warning">
            {notice}
          </p>
        )}

        <Field label="Username">
          <input
            name="username"
            autoComplete="username"
            required
            minLength={creating ? 3 : 1}
            maxLength={32}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className={INPUT}
          />
        </Field>
        <Field label="Password" hint={creating ? "At least 8 characters." : undefined}>
          <input
            name="password"
            type="password"
            autoComplete={creating ? "new-password" : "current-password"}
            required
            minLength={creating ? 8 : 1}
            maxLength={128}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={INPUT}
          />
        </Field>
        {creating && config.invite_required && (
          <Field label="Invite code">
            <input
              name="invite"
              autoComplete="off"
              required
              value={invite}
              onChange={(event) => setInvite(event.target.value)}
              className={INPUT}
            />
          </Field>
        )}

        {error && (
          <p
            id={errorId}
            className="rounded-lg bg-down/10 px-3 py-2 text-sm text-down"
            role="alert"
          >
            {error}
          </p>
        )}

        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          <LockIcon aria-hidden="true" />
          {busy ? `${action}…` : action}
        </Button>

        {config.signup && (
          <p className="text-center text-sm text-muted-foreground">
            {creating ? "Already have an account?" : "New here?"}{" "}
            <button
              type="button"
              className="cursor-pointer font-medium text-primary hover:underline"
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
