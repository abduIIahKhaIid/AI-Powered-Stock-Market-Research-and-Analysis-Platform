import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useChat } from "./chat/useChat";
import Composer from "./components/Composer";
import MessageView from "./components/MessageView";
import ModeToggle from "./components/ModeToggle";
import Sidebar from "./components/Sidebar";
import StarterPrompts from "./components/StarterPrompts";

// Keep following the stream only while the reader is near the bottom.
const STICK_THRESHOLD_PX = 120;

export default function App() {
  const chat = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const active = chat.activeConversation;
  const messages = useMemo(() => active?.messages ?? [], [active]);

  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [messages]);

  function onScroll() {
    const element = scrollRef.current;
    if (!element) return;
    stickToBottom.current =
      element.scrollHeight - element.scrollTop - element.clientHeight < STICK_THRESHOLD_PX;
  }

  function send(text: string) {
    stickToBottom.current = true;
    chat.send(text);
  }

  function select(id: string) {
    stickToBottom.current = true;
    chat.select(id);
    setSidebarOpen(false);
  }

  function newChat() {
    chat.newChat();
    setSidebarOpen(false);
  }

  return (
    <div className="app">
      <Sidebar
        conversations={chat.conversations}
        activeId={active?.id ?? null}
        open={sidebarOpen}
        onSelect={select}
        onNew={newChat}
        onDelete={chat.remove}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="chat">
        <header className="chat-header">
          <button
            type="button"
            className="icon-button menu-button"
            onClick={() => setSidebarOpen(true)}
          >
            <span aria-hidden="true">☰</span>
            <span className="visually-hidden">Open conversations</span>
          </button>
          <h1 className="chat-title">{active?.title ?? "New chat"}</h1>
          <ModeToggle mode={chat.mode} onChange={chat.setMode} />
        </header>

        <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
          <div className="chat-column">
            {messages.length === 0 ? (
              <StarterPrompts mode={chat.mode} onPick={send} />
            ) : (
              <div className="messages" aria-live="polite">
                {messages.map((message) => (
                  <MessageView key={message.id} message={message} />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="chat-column">
          <Composer streaming={chat.streaming} onSend={send} onStop={chat.stop} />
        </div>
      </main>
    </div>
  );
}
