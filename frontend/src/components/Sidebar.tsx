import {
  LogOutIcon,
  MessageSquareIcon,
  PanelLeftCloseIcon,
  SearchIcon,
  SquarePenIcon,
  Trash2Icon,
  TrendingUpIcon,
  XIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { Conversation } from "../chat/types";
import type { SavedAnalysis } from "../jobs/types";
import { cn } from "../lib/utils";
import HealthBadge from "./HealthBadge";
import SavedAnalyses from "./SavedAnalyses";
import { Button } from "./ui/button";
import { Tooltip } from "./ui/tooltip";

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  /** Drawer open on small screens. */
  open: boolean;
  /** Folded away on large screens. */
  collapsed?: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
  onCollapse?: () => void;
  onOpenAnalysis: (analysis: SavedAnalysis) => void;
  analysesKey?: number;
  user?: { username: string; onSignOut: () => void };
}

const DAY = 24 * 60 * 60 * 1000;

/** Chainlit-style date groups for the thread list. */
function groupOf(timestamp: number, now = new Date()): string {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (timestamp >= startOfToday) return "Today";
  if (timestamp >= startOfToday - DAY) return "Yesterday";
  if (timestamp >= startOfToday - 7 * DAY) return "Previous 7 days";
  if (timestamp >= startOfToday - 30 * DAY) return "Previous 30 days";
  return "Older";
}

function shortTime(timestamp: number): string {
  const date = new Date(timestamp);
  if (date.toDateString() === new Date().toDateString()) {
    return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export default function Sidebar(props: Props) {
  const { conversations, activeId, open, collapsed, onSelect, onNew, onDelete, onClose, user } =
    props;
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const shown = needle
      ? conversations.filter((conversation) => conversation.title.toLowerCase().includes(needle))
      : conversations;
    const map = new Map<string, Conversation[]>();
    for (const conversation of shown) {
      const group = groupOf(conversation.updatedAt);
      map.set(group, [...(map.get(group) ?? []), conversation]);
    }
    return [...map.entries()];
  }, [conversations, query]);

  return (
    <>
      <aside
        aria-label="Conversations"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-border bg-sidebar transition-[transform,width,margin] duration-300 ease-out",
          "lg:static lg:z-auto lg:translate-x-0",
          open ? "translate-x-0 shadow-2xl lg:shadow-none" : "-translate-x-full",
          collapsed && "lg:-ml-72",
        )}
      >
        <div className="flex h-14 items-center justify-between gap-2 px-3">
          <span className="flex items-center gap-2 px-1 text-[15px] font-semibold tracking-tight">
            <span
              className="grid size-7 place-items-center rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-emerald-500 text-white"
              aria-hidden="true"
            >
              <TrendingUpIcon className="size-4" strokeWidth={2.5} />
            </span>
            Stock Research
          </span>
          <div className="flex items-center">
            {props.onCollapse && (
              <Tooltip content="Hide sidebar" side="right">
                <Button
                  size="icon-sm"
                  variant="ghost"
                  className="hidden lg:inline-flex"
                  aria-label="Hide sidebar"
                  onClick={props.onCollapse}
                >
                  <PanelLeftCloseIcon />
                </Button>
              </Tooltip>
            )}
            <Button
              size="icon-sm"
              variant="ghost"
              className="lg:hidden"
              aria-label="Close conversations"
              onClick={onClose}
            >
              <XIcon />
            </Button>
          </div>
        </div>

        <div className="space-y-2 px-3 pb-2">
          <Button variant="outline" className="w-full justify-start" onClick={onNew}>
            <SquarePenIcon aria-hidden="true" />
            New chat
          </Button>
          <label className="relative block">
            <span className="sr-only">Search conversations</span>
            <SearchIcon
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search chats"
              className="h-8 w-full rounded-lg border border-transparent bg-muted/70 pr-2 pl-8 text-sm outline-none placeholder:text-muted-foreground/80 focus:border-primary/30 focus:bg-card"
            />
          </label>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 scrollbar-thin">
          {conversations.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-muted-foreground">
              Your conversations will appear here.
            </p>
          ) : groups.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-muted-foreground">No chats match.</p>
          ) : (
            groups.map(([group, items]) => (
              <div key={group} className="mb-2">
                <h3 className="px-3 pt-2 pb-1 text-[11px] font-semibold tracking-wide text-muted-foreground/80 uppercase">
                  {group}
                </h3>
                <ul>
                  {items.map((conversation) => {
                    const active = conversation.id === activeId;
                    return (
                      <li key={conversation.id} className="group relative">
                        <button
                          type="button"
                          aria-current={active ? "true" : undefined}
                          onClick={() => onSelect(conversation.id)}
                          className={cn(
                            "flex w-full cursor-pointer items-center gap-2 rounded-lg py-2 pr-9 pl-3 text-left text-sm transition-colors",
                            active
                              ? "bg-accent font-medium text-accent-foreground"
                              : "text-foreground/80 hover:bg-muted hover:text-foreground",
                          )}
                        >
                          <MessageSquareIcon
                            className="size-3.5 shrink-0 opacity-50"
                            aria-hidden="true"
                          />
                          <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
                          <span className="shrink-0 text-[10px] text-muted-foreground group-hover:opacity-0">
                            {shortTime(conversation.updatedAt)}
                          </span>
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete “${conversation.title}”`}
                          onClick={() => onDelete(conversation.id)}
                          className="absolute top-1/2 right-1.5 grid size-6 -translate-y-1/2 cursor-pointer place-items-center rounded-md text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-down/10 hover:text-down focus-visible:opacity-100"
                        >
                          <Trash2Icon className="size-3.5" aria-hidden="true" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
          )}
        </nav>

        <SavedAnalyses onOpen={props.onOpenAnalysis} refreshKey={props.analysesKey} />

        <footer className="space-y-2 border-t border-border p-3">
          <HealthBadge />
          {user && (
            <div className="flex items-center gap-2 rounded-lg bg-muted/60 p-1.5">
              <span
                className="grid size-7 place-items-center rounded-full bg-primary/15 text-xs font-semibold text-primary uppercase"
                aria-hidden="true"
              >
                {user.username.slice(0, 1)}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium" title="Signed in">
                {user.username}
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs"
                onClick={user.onSignOut}
              >
                <LogOutIcon className="size-3.5" aria-hidden="true" />
                Sign out
              </Button>
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">NASDAQ only · Not financial advice</p>
        </footer>
      </aside>
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/30 backdrop-blur-[1px] lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
    </>
  );
}
