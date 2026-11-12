import type { Conversation } from "../chat/types";
import HealthBadge from "./HealthBadge";

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  open: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

function shortDate(timestamp: number): string {
  const date = new Date(timestamp);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export default function Sidebar(props: Props) {
  const { conversations, activeId, open, onSelect, onNew, onDelete, onClose } = props;
  return (
    <>
      <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Conversations">
        <div className="sidebar-head">
          <span className="brand">
            <span className="brand-mark" aria-hidden="true">
              ▲
            </span>
            Stock Research
          </span>
          <button type="button" className="icon-button close-button" onClick={onClose}>
            <span aria-hidden="true">×</span>
            <span className="visually-hidden">Close conversations</span>
          </button>
        </div>

        <button type="button" className="new-chat" onClick={onNew}>
          + New chat
        </button>

        <nav className="conversation-list">
          {conversations.length === 0 ? (
            <p className="muted small sidebar-empty">Your conversations will appear here.</p>
          ) : (
            <ul>
              {conversations.map((conversation) => (
                <li
                  key={conversation.id}
                  className={conversation.id === activeId ? "active" : undefined}
                >
                  <button
                    type="button"
                    className="conversation"
                    aria-current={conversation.id === activeId ? "true" : undefined}
                    onClick={() => onSelect(conversation.id)}
                  >
                    <span className="conversation-title">{conversation.title}</span>
                    <span className="conversation-date">{shortDate(conversation.updatedAt)}</span>
                  </button>
                  <button
                    type="button"
                    className="conversation-delete"
                    aria-label={`Delete “${conversation.title}”`}
                    onClick={() => onDelete(conversation.id)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>

        <footer className="sidebar-foot">
          <HealthBadge />
          <p className="muted small">NASDAQ only · Not financial advice</p>
        </footer>
      </aside>
      {open && <div className="backdrop" onClick={onClose} aria-hidden="true" />}
    </>
  );
}
