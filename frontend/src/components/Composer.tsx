import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

export const MAX_MESSAGE_LENGTH = 4000;

interface Props {
  streaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

export default function Composer({ streaming, onSend, onStop }: Props) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Grow with the text, up to the max height set in CSS.
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

  return (
    <form className="composer" onSubmit={submit}>
      <div className="composer-box">
        <label htmlFor="chat-input" className="visually-hidden">
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
        />
        {streaming ? (
          <button type="button" className="send stop" onClick={onStop}>
            Stop
          </button>
        ) : (
          <button type="submit" className="send" disabled={!text.trim()}>
            Send
          </button>
        )}
      </div>
      <p className="composer-note">
        Educational information, not financial advice. Enter to send, Shift+Enter for a new line.
      </p>
    </form>
  );
}
