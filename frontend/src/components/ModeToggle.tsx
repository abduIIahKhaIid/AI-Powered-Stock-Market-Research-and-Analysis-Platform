import type { Mode } from "../chat/types";

const OPTIONS: { value: Mode; label: string; hint: string }[] = [
  { value: "simple", label: "Simple", hint: "Short answers in plain words" },
  { value: "detailed", label: "Detailed", hint: "Figures, formulas and caveats" },
];

interface Props {
  mode: Mode;
  onChange: (mode: Mode) => void;
}

export default function ModeToggle({ mode, onChange }: Props) {
  return (
    <div className="mode-toggle" role="radiogroup" aria-label="Explanation mode">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={mode === option.value}
          title={option.hint}
          className={mode === option.value ? "selected" : undefined}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
