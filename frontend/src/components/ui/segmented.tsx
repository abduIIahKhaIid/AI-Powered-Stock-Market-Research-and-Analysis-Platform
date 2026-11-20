import { m } from "motion/react";
import { useId, type ReactNode } from "react";
import { cn } from "../../lib/utils";
import { useAnimate } from "../../settings/context";

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  /** Accessible name when the label is an icon. */
  name?: string;
  hint?: string;
}

interface Props<T extends string> {
  value: T;
  options: SegmentOption<T>[];
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "default";
  className?: string;
}

/** A radio group drawn as a segmented control; the highlight slides to the chosen option. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = "default",
  className,
}: Props<T>) {
  const id = useId();
  const animate = useAnimate();
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn("inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5", className)}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={option.name}
            title={option.hint}
            onClick={() => onChange(option.value)}
            className={cn(
              "relative inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-md font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
              size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-sm",
              selected ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {selected && (
              <m.span
                layoutId={animate ? `segment-${id}` : undefined}
                className="absolute inset-0 rounded-md bg-card shadow-sm ring-1 ring-border/60"
                transition={{ type: "spring", stiffness: 500, damping: 38 }}
              />
            )}
            <span className="relative z-10 inline-flex items-center gap-1.5">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
