import { STARTER_PROMPTS } from "../chat/starters";
import type { Mode } from "../chat/types";

interface Props {
  mode: Mode;
  onPick: (prompt: string) => void;
}

export default function StarterPrompts({ mode, onPick }: Props) {
  return (
    <section className="empty-state" aria-labelledby="empty-title">
      <h2 id="empty-title">Ask about any NASDAQ stock</h2>
      <p className="muted">
        Answers are built from live market data, and every number shows where it came from.
        {mode === "simple"
          ? " Simple mode keeps explanations short and jargon-free."
          : " Detailed mode adds figures, formulas and caveats."}
      </p>
      <ul className="starter-grid" aria-label="Starter prompts">
        {STARTER_PROMPTS.map((starter) => (
          <li key={starter.prompt}>
            <button type="button" className="starter" onClick={() => onPick(starter.prompt)}>
              <span className="starter-label">{starter.label}</span>
              <span className="starter-text">{starter.prompt}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
