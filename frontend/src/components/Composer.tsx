import { ArrowUpIcon, SquareIcon } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";

export const MAX_MESSAGE_LENGTH = 4000;

interface Props {
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  /** Controls shown at the bottom left of the box (the mode toggle). */
  tools?: ReactNode;
}

export default function Composer({ streaming, onSend, onStop, tools }: Props) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Grow with the text, up to max-h.
  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  }, [text]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (streaming || !text.trim()) return;
    onSend(text);
    setText("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) submit(event);
  }

  const nearLimit = text.length > MAX_MESSAGE_LENGTH * 0.8;

  return (
    <form className="pb-3" onSubmit={submit}>
      <div
        className={cn(
          "rounded-2xl border border-border bg-card shadow-lg shadow-black/[0.03] transition-all",
          "focus-within:border-primary/40 focus-within:ring-4 focus-within:ring-primary/10",
        )}
      >
        <label htmlFor="chat-input" className="sr-only">
          Ask a question
        </label>
        <textarea
          id="chat-input"
          ref={inputRef}
          rows={1}
          value={text}
          maxLength={MAX_MESSAGE_LENGTH}
          placeholder="Ask about a NASDAQ stock, e.g. “How did Tesla move this week?”"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          className="block max-h-52 min-h-[52px] w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground/70 scrollbar-thin"
        />
        <div className="flex items-center justify-between gap-2 px-2.5 pb-2.5">
          <div className="flex min-w-0 items-center gap-2">{tools}</div>
          <div className="flex items-center gap-2">
            {nearLimit && (
              <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                {text.length}/{MAX_MESSAGE_LENGTH}
              </span>
            )}
            {streaming ? (
              <Button
                type="button"
                size="icon-sm"
                variant="secondary"
                aria-label="Stop"
                onClick={onStop}
                className="rounded-full"
              >
                <SquareIcon className="size-3 fill-current" aria-hidden="true" />
              </Button>
            ) : (
              <Button
                type="submit"
                size="icon-sm"
                aria-label="Send"
                disabled={!text.trim()}
                className="rounded-full"
              >
                <ArrowUpIcon aria-hidden="true" strokeWidth={2.5} />
              </Button>
            )}
          </div>
        </div>
      </div>
      <p className="mt-2 text-center text-[11px] text-muted-foreground">
        Educational information, not financial advice. Enter to send, Shift+Enter for a new line.
      </p>
    </form>
  );
}
