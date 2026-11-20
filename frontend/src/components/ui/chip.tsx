import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

/** A small pill button; `aria-pressed` or `aria-expanded` gives it the selected look. */
export function Chip({ className, ...props }: ComponentProps<"button">) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-7 cursor-pointer items-center gap-1 rounded-full border border-border bg-card px-2.5 text-xs font-medium text-muted-foreground transition-all outline-none",
        "hover:border-primary/40 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 active:scale-95",
        "aria-pressed:border-primary/40 aria-pressed:bg-primary/10 aria-pressed:text-primary",
        "aria-expanded:border-primary/40 aria-expanded:bg-primary/10 aria-expanded:text-primary",
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-border disabled:hover:text-muted-foreground [&_svg]:size-3.5",
        className,
      )}
      {...props}
    />
  );
}
