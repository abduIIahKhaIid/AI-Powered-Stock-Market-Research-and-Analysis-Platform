/** The card around every chart and table: slides and fades in when it first appears. */
import { m } from "motion/react";
import type { ReactNode } from "react";
import { cn } from "../lib/utils";
import { useAnimate } from "../settings/context";

interface Props {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  /** Controls on the right of the title (periods, views). */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  busy?: boolean;
}

export default function ChartFrame({
  title,
  subtitle,
  icon,
  actions,
  children,
  className,
  busy,
}: Props) {
  const animate = useAnimate();
  return (
    <m.figure
      aria-busy={busy}
      initial={animate ? { opacity: 0, y: 14, scale: 0.985 } : false}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
      className={cn(
        "relative my-1 overflow-hidden rounded-2xl border border-border bg-card shadow-xs",
        className,
      )}
    >
      {busy && (
        <span className="absolute inset-x-0 top-0 h-0.5 overflow-hidden" aria-hidden="true">
          <span className="block h-full w-1/3 animate-indeterminate bg-primary" />
        </span>
      )}
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-4 pt-3.5 pb-2">
        <div className="flex min-w-0 items-start gap-2.5">
          {icon && (
            <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary [&_svg]:size-4">
              {icon}
            </span>
          )}
          <div className="min-w-0">
            <figcaption className="text-sm font-semibold text-foreground">{title}</figcaption>
            {subtitle && <div className="mt-0.5 text-xs text-muted-foreground">{subtitle}</div>}
          </div>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-1.5">{actions}</div>}
      </div>
      {children}
    </m.figure>
  );
}

/** Footer line under a chart: where the data came from. */
export function ChartFoot({ children }: { children: ReactNode }) {
  return (
    <p className="border-t border-border/70 bg-muted/30 px-4 py-2 text-[11px] text-muted-foreground [&_a]:text-primary [&_a]:hover:underline">
      {children}
    </p>
  );
}
