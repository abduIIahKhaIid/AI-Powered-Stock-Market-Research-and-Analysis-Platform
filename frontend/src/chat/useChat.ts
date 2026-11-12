/** Conversation state for the chat screen: sending, streaming, stopping and saving. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { watchJob } from "./jobs";
import {
  applyEvent,
  applyJobProgress,
  finishMessage,
  jobNeedsWatching,
  jobReportMessage,
  newAssistantMessage,
} from "./reducer";
import { ChatHttpError, streamChat } from "./sse";
import {
  loadConversations,
  loadMode,
  newId,
  saveConversations,
  saveMode,
  titleFrom,
} from "./storage";
import type {
  AssistantMessage,
  Conversation,
  JobDoneData,
  JobItem,
  JobProgressData,
  Mode,
  UserMessage,
} from "./types";

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
  /** Goes up each time a background job finishes, so lists of saved results can refresh. */
  jobsFinished: number;
}

/** Ids of the jobs that still need their progress stream, with where they live. */
function jobsToWatch(conversations: Conversation[]): string {
  const ids: string[] = [];
  for (const conversation of conversations) {
    for (const message of conversation.messages) {
      if (message.role !== "assistant") continue;
      for (const job of message.jobs ?? []) {
        if (jobNeedsWatching(job)) ids.push(job.id);
      }
    }
  }
  return ids.sort().join(",");
}

function updateJob(
  conversations: Conversation[],
  jobId: string,
  change: (job: JobItem) => JobItem,
): Conversation[] {
  return conversations.map((conversation) => {
    let touched = false;
    const messages = conversation.messages.map((message) => {
      if (message.role !== "assistant" || !message.jobs?.some((job) => job.id === jobId)) {
        return message;
      }
      touched = true;
      return {
        ...message,
        jobs: message.jobs.map((job) => (job.id === jobId ? change(job) : job)),
      };
    });
    return touched ? { ...conversation, messages } : conversation;
  });
}

/** Mark the job finished and post its summary right after the answer that started it. */
function reportJob(conversations: Conversation[], done: JobDoneData): Conversation[] {
  return conversations.map((conversation) => {
    const index = conversation.messages.findIndex(
      (message) => message.role === "assistant" && message.jobs?.some((job) => job.id === done.id),
    );
    if (index === -1) return conversation;
    const owner = conversation.messages[index] as AssistantMessage;
    const job = owner.jobs?.find((item) => item.id === done.id);
    if (!job || job.reported) return conversation;
    const updated: AssistantMessage = {
      ...owner,
      jobs: owner.jobs?.map((item) =>
        item.id === done.id
          ? {
              ...item,
              status: done.status,
              progress: done.status === "succeeded" ? 100 : item.progress,
              reported: true,
            }
          : item,
      ),
    };
    const already = conversation.messages.some(
      (message) => message.role === "assistant" && message.reportFor === done.id,
    );
    const messages = [...conversation.messages];
    messages[index] = updated;
    if (!already) messages.push(jobReportMessage(newId(), owner.mode, done));
    return { ...conversation, messages, updatedAt: Date.now() };
  });
}

export function useChat(): ChatController {
  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [mode, setModeState] = useState<Mode>(loadMode);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [jobsFinished, setJobsFinished] = useState(0);
  const watching = useMemo(() => jobsToWatch(conversations), [conversations]);

  // One progress stream per unfinished job, also for jobs started before a page reload.
  useEffect(() => {
    if (!watching) return;
    const stops = watching.split(",").map((jobId) =>
      watchJob(jobId, {
        onProgress: (data: JobProgressData) =>
          setConversations((list) => updateJob(list, jobId, (job) => applyJobProgress(job, data))),
        onDone: (data: JobDoneData) => {
          setConversations((list) => reportJob(list, data));
          setJobsFinished((count) => count + 1);
        },
      }),
    );
    return () => stops.forEach((stop) => stop());
  }, [watching]);

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
    jobsFinished,
  };
}
