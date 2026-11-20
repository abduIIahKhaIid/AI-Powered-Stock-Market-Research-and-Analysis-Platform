import {
  BadgeDollarSignIcon,
  ChartLineIcon,
  GitCompareIcon,
  GraduationCapIcon,
  LanguagesIcon,
  LineChartIcon,
  TrendingUpIcon,
} from "lucide-react";
import { m } from "motion/react";
import { STARTER_PROMPTS, type StarterIcon } from "../chat/starters";
import type { Mode } from "../chat/types";
import { useAnimate } from "../settings/context";

const ICONS: Record<StarterIcon, typeof TrendingUpIcon> = {
  price: BadgeDollarSignIcon,
  trend: ChartLineIcon,
  learn: GraduationCapIcon,
  language: LanguagesIcon,
  compare: GitCompareIcon,
  scenario: LineChartIcon,
};

const TINTS = [
  "bg-indigo-500/10 text-indigo-600 dark:text-indigo-300",
  "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
  "bg-amber-500/10 text-amber-600 dark:text-amber-300",
  "bg-fuchsia-500/10 text-fuchsia-600 dark:text-fuchsia-300",
];

interface Props {
  mode: Mode;
  onPick: (prompt: string) => void;
}

export default function StarterPrompts({ mode, onPick }: Props) {
  const animate = useAnimate();
  return (
    <section
      className="mx-auto flex min-h-full max-w-2xl flex-col items-center justify-center py-10 text-center"
      aria-labelledby="empty-title"
    >
      <m.div
        initial={animate ? { opacity: 0, scale: 0.8, rotate: -8 } : false}
        animate={{ opacity: 1, scale: 1, rotate: 0 }}
        transition={{ type: "spring", stiffness: 260, damping: 18 }}
        className="mb-5 grid size-14 place-items-center rounded-2xl bg-gradient-to-br from-indigo-500 via-violet-500 to-emerald-500 text-white shadow-lg shadow-indigo-500/25"
        aria-hidden="true"
      >
        <TrendingUpIcon className="size-7" strokeWidth={2.5} />
      </m.div>
      <h2 id="empty-title" className="text-2xl font-semibold tracking-tight sm:text-3xl">
        Ask about any NASDAQ stock
      </h2>
      <p className="mt-2 max-w-lg text-sm text-muted-foreground">
        Answers are built from live market data, and every number shows where it came from.
        {mode === "simple"
          ? " Simple mode keeps explanations short and jargon-free."
          : " Detailed mode adds figures, formulas and caveats."}
      </p>
      <ul
        className="mt-8 grid w-full grid-cols-1 gap-3 sm:grid-cols-2"
        aria-label="Starter prompts"
      >
        {STARTER_PROMPTS.map((starter, index) => {
          const Icon = ICONS[starter.icon];
          return (
            <m.li
              key={starter.prompt}
              initial={animate ? { opacity: 0, y: 12 } : false}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: animate ? 0.1 + index * 0.06 : 0, duration: 0.35 }}
            >
              <button
                type="button"
                onClick={() => onPick(starter.prompt)}
                className="group flex h-full w-full cursor-pointer items-start gap-3 rounded-xl border border-border bg-card p-3.5 text-left shadow-xs transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
              >
                <span
                  className={`grid size-9 shrink-0 place-items-center rounded-lg ${TINTS[index % TINTS.length]}`}
                  aria-hidden="true"
                >
                  <Icon className="size-4.5" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-foreground">
                    {starter.label}
                  </span>
                  <span className="mt-0.5 block text-[13px] leading-snug text-muted-foreground group-hover:text-foreground/80">
                    {starter.prompt}
                  </span>
                </span>
              </button>
            </m.li>
          );
        })}
      </ul>
    </section>
  );
}
