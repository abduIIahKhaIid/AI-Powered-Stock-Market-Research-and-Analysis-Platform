/**
 * Saved conversations and the chosen explanation mode, kept in this browser.
 * Storage can be unavailable (private windows, blocked cookies), so every access is guarded.
 */

import type { ChatMessage, Conversation, Mode } from "./types";

const CONVERSATIONS_KEY = "stock-research.conversations.v1";
const MODE_KEY = "stock-research.mode";
export const MAX_CONVERSATIONS = 50;

function interrupted(message: ChatMessage): ChatMessage {
  // An answer that was still streaming when the page closed can never finish.
  if (message.role === "assistant" && message.state === "streaming") {
    return { ...message, state: "stopped", statusText: undefined };
  }
  return message;
}

function isConversation(value: unknown): value is Conversation {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<Conversation>;
  return typeof item.id === "string" && Array.isArray(item.messages);
}

export function loadConversations(): Conversation[] {
  try {
    const raw = window.localStorage.getItem(CONVERSATIONS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isConversation).map((conversation) => ({
      ...conversation,
      title: conversation.title || "Untitled chat",
      messages: conversation.messages.map(interrupted),
    }));
  } catch {
    return [];
  }
}

export function saveConversations(conversations: Conversation[]): void {
  try {
    window.localStorage.setItem(
      CONVERSATIONS_KEY,
      JSON.stringify(conversations.slice(0, MAX_CONVERSATIONS)),
    );
  } catch {
    // Quota exceeded or storage blocked: the chat keeps working for this visit.
  }
}

export function loadMode(): Mode {
  try {
    return window.localStorage.getItem(MODE_KEY) === "detailed" ? "detailed" : "simple";
  } catch {
    return "simple";
  }
}

export function saveMode(mode: Mode): void {
  try {
    window.localStorage.setItem(MODE_KEY, mode);
  } catch {
    // Ignore: the toggle still works for this visit.
  }
}

export function titleFrom(message: string, maxLength = 60): string {
  const text = message.replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength - 1).trimEnd()}…` : text;
}

export function newId(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}
