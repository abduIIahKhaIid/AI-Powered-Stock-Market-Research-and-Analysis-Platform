/** "Sources" and "Assumptions" chips under a chart or table; each opens its list (SCRUM-37). */
import { ExternalLinkIcon, LightbulbIcon, LinkIcon } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import type { DetailSource } from "../chat/types";
import { Chip } from "./ui/chip";

interface Props {
  sources?: DetailSource[];
  assumptions?: string[];
  /** More controls for the same row, such as the CSV export. */
  children?: ReactNode;
}

type Panel = "sources" | "assumptions";

export default function DetailChips({ sources = [], assumptions = [], children }: Props) {
  const [open, setOpen] = useState<Panel | null>(null);
  const id = useId();
  const toggle = (panel: Panel) => setOpen((current) => (current === panel ? null : panel));

  return (
    <div className="px-4 pb-3">
      <div className="flex flex-wrap gap-1.5">
        <Chip
          aria-expanded={open === "sources"}
          aria-controls={`${id}-sources`}
          disabled={sources.length === 0}
          onClick={() => toggle("sources")}
        >
          <LinkIcon aria-hidden="true" />
          Sources ({sources.length})
        </Chip>
        <Chip
          aria-expanded={open === "assumptions"}
          aria-controls={`${id}-assumptions`}
          disabled={assumptions.length === 0}
          onClick={() => toggle("assumptions")}
        >
          <LightbulbIcon aria-hidden="true" />
          Assumptions ({assumptions.length})
        </Chip>
        {children}
      </div>
      {open === "sources" && (
        <ul
          id={`${id}-sources`}
          aria-label="Sources"
          className="mt-2 animate-fade-up space-y-1 rounded-lg border border-border bg-muted/40 p-2.5 text-xs"
        >
          {sources.map((source) => (
            <li key={`${source.label}|${source.link ?? ""}`} className="flex items-start gap-1.5">
              <span className="mt-1.5 size-1 shrink-0 rounded-full bg-primary" aria-hidden="true" />
              {source.link ? (
                <a
                  href={source.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-primary hover:underline"
                >
                  {source.label}
                  <ExternalLinkIcon className="size-3" aria-hidden="true" />
                </a>
              ) : (
                <span className="text-foreground">{source.label}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {open === "assumptions" && (
        <ul
          id={`${id}-assumptions`}
          aria-label="Assumptions"
          className="mt-2 animate-fade-up list-disc space-y-1 rounded-lg border border-border bg-muted/40 py-2.5 pr-2.5 pl-6 text-xs text-foreground"
        >
          {assumptions.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
