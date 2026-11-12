/** Conversation state for the chat screen: sending, streaming, stopping and saving. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { applyEvent, finishMessage, newAssistantMessage } from "./reducer";
import { ChatHttpError, streamChat } from "./sse";
import {
  loadConversations,
  loadMode,
  newId,
  saveConversations,
  saveMode,
  titleFrom,
} from "./storage";
import type { AssistantMessage, Conversation, Mode, UserMessage } from "./types";

export const INCOMPLETE_MESSAGE =
  "The connection closed before the answer finished. Please ask again.";

export interface ChatController {
  conversations: Conversation[];
  activeConversation: Conversation | null;
  mode: Mode;
  streaming: boolean;
  send: (text: string) => void;
  stop: () => void;
  newChat: () => void;
  select: (id: string) => void;
  remove: (id: string) => void;
  setMode: (mode: Mode) => void;
}

export function useChat(): ChatController {
  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [mode, setModeState] = useState<Mode>(loadMode);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Saving on every streamed token would be wasteful; save once the answer settles.
  useEffect(() => {
    if (!streaming) saveConversations(conversations);
  }, [conversations, streaming]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? null,
    [conversations, activeId],
  );

  const setMode = useCallback((next: Mode) => {
    setModeState(next);
    saveMode(next);
  }, []);

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || abortRef.current) return;

      const now = Date.now();
      const user: UserMessage = { id: newId(), role: "user", text: message, mode };
      const assistant = newAssistantMessage(newId(), mode);
      const existing = conversations.find((conversation) => conversation.id === activeId);
      const conversationId = existing?.id ?? newId();

      if (existing) {
        setConversations((list) => [
          { ...existing, updatedAt: now, messages: [...existing.messages, user, assistant] },
          ...list.filter((conversation) => conversation.id !== existing.id),
        ]);
      } else {
        const created: Conversation = {
          id: conversationId,
          serverId: null,
          title: titleFrom(message),
          createdAt: now,
          updatedAt: now,
          messages: [user, assistant],
        };
        setConversations((list) => [created, ...list]);
        setActiveId(conversationId);
      }

      const update = (change: (conversation: Conversation) => Conversation) =>
        setConversations((list) =>
          list.map((conversation) =>
            conversation.id === conversationId ? change(conversation) : conversation,
          ),
        );
      const updateAssistant = (change: (message: AssistantMessage) => AssistantMessage) =>
        update((conversation) => ({
          ...conversation,
          messages: conversation.messages.map((item) =>
            item.id === assistant.id && item.role === "assistant" ? change(item) : item,
          ),
        }));

      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(true);

      streamChat(
        { message, mode, conversation_id: existing?.serverId ?? null },
        (event) => {
          if (event.type === "conversation") {
            update((conversation) => ({ ...conversation, serverId: event.data.conversation_id }));
            return;
          }
          updateAssistant((item) => applyEvent(item, event));
        },
        controller.signal,
      )
        .then(() =>
          updateAssistant((item) =>
            finishMessage(item, { code: "incomplete", message: INCOMPLETE_MESSAGE }),
          ),
        )
        .catch((error: unknown) => {
          if (controller.signal.aborted) {
            updateAssistant((item) => finishMessage(item, "stopped"));
            return;
          }
          const code = error instanceof ChatHttpError ? `http_${error.status}` : "network";
          const text =
            error instanceof ChatHttpError
              ? error.message
              : "Could not reach the API. Check that the backend is running and try again.";
          updateAssistant((item) => finishMessage(item, { code, message: text }));
        })
        .finally(() => {
          if (abortRef.current === controller) abortRef.current = null;
          setStreaming(false);
        });
    },
    [activeId, conversations, mode],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const newChat = useCallback(() => setActiveId(null), []);

  const select = useCallback((id: string) => setActiveId(id), []);

  const remove = useCallback((id: string) => {
    setConversations((list) => list.filter((conversation) => conversation.id !== id));
    setActiveId((current) => (current === id ? null : current));
  }, []);

  return {
    conversations,
    activeConversation,
    mode,
    streaming,
    send,
    stop,
    newChat,
    select,
    remove,
    setMode,
  };
}
