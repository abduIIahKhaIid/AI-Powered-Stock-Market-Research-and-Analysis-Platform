import {
  ArrowDownIcon,
  MenuIcon,
  MoonIcon,
  PanelLeftOpenIcon,
  Settings2Icon,
  SunIcon,
} from "lucide-react";
import { AnimatePresence, LazyMotion, m } from "motion/react";
import { lazy, Suspense, useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useChat } from "./chat/useChat";
import Composer from "./components/Composer";
import MessageView from "./components/MessageView";
import ModeToggle from "./components/ModeToggle";
import Sidebar from "./components/Sidebar";
import StarterPrompts from "./components/StarterPrompts";
import { Button } from "./components/ui/button";
import { Tooltip } from "./components/ui/tooltip";
import type { SavedAnalysis } from "./jobs/types";
import { useSettings } from "./settings/context";
import SettingsProvider from "./settings/SettingsProvider";

// Keep following the stream only while the reader is near the bottom.
const STICK_THRESHOLD_PX = 120;
const SIDEBAR_KEY = "stock-research.sidebar-collapsed";
// Dialogs are loaded when first opened.
const AnalysisView = lazy(() => import("./components/AnalysisView"));
const SettingsDialog = lazy(() => import("./components/SettingsDialog"));
const loadMotionFeatures = () => import("./lib/motionFeatures").then((module) => module.default);

interface Props {
  /** The signed-in user, when the server has sign-in turned on (SCRUM-40). */
  user?: { username: string; onSignOut: () => void };
}

function loadCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}

function ThemeButton() {
  const { resolvedTheme, update } = useSettings();
  const dark = resolvedTheme === "dark";
  return (
    <Tooltip content={dark ? "Light theme" : "Dark theme"} side="bottom">
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
        onClick={() => update({ theme: dark ? "light" : "dark" })}
      >
        {dark ? <SunIcon /> : <MoonIcon />}
      </Button>
    </Tooltip>
  );
}

function ChatScreen({ user }: Props) {
  const chat = useChat();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [openAnalysis, setOpenAnalysis] = useState<SavedAnalysis | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const closeAnalysis = useCallback(() => setOpenAnalysis(null), []);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const active = chat.activeConversation;
  const messages = useMemo(() => active?.messages ?? [], [active]);
  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");

  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [messages]);

  function onScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const near =
      element.scrollHeight - element.scrollTop - element.clientHeight < STICK_THRESHOLD_PX;
    stickToBottom.current = near;
    setAtBottom(near);
  }

  function scrollToBottom() {
    const element = scrollRef.current;
    stickToBottom.current = true;
    element?.scrollTo?.({ top: element.scrollHeight, behavior: "smooth" });
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

  function showAnalysis(analysis: SavedAnalysis) {
    setOpenAnalysis(analysis);
    setSidebarOpen(false);
  }

  function newChat() {
    chat.newChat();
    setSidebarOpen(false);
  }

  function toggleCollapsed(next: boolean) {
    setCollapsed(next);
    try {
      window.localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
    } catch {
      // Storage blocked: keep the choice for this visit.
    }
  }

  return (
    <div className="flex h-full overflow-hidden bg-background">
      <a
        href="#chat-input"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to the message box
      </a>
      <Sidebar
        conversations={chat.conversations}
        activeId={active?.id ?? null}
        open={sidebarOpen}
        collapsed={collapsed}
        onSelect={select}
        onNew={newChat}
        onDelete={chat.remove}
        onClose={() => setSidebarOpen(false)}
        onCollapse={() => toggleCollapsed(true)}
        onOpenAnalysis={showAnalysis}
        analysesKey={chat.jobsFinished}
        user={user}
      />

      <main className="relative flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border/70 bg-background/80 px-3 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <Button
            size="icon-sm"
            variant="ghost"
            className="lg:hidden"
            aria-label="Open conversations"
            onClick={() => setSidebarOpen(true)}
          >
            <MenuIcon />
          </Button>
          {collapsed && (
            <Tooltip content="Show sidebar" side="bottom">
              <Button
                size="icon-sm"
                variant="ghost"
                className="hidden lg:inline-flex"
                aria-label="Show sidebar"
                onClick={() => toggleCollapsed(false)}
              >
                <PanelLeftOpenIcon />
              </Button>
            </Tooltip>
          )}
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">
            {active?.title ?? "New chat"}
          </h1>
          <ThemeButton />
          <Tooltip content="Settings" side="bottom">
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="Settings"
              onClick={() => setSettingsOpen(true)}
            >
              <Settings2Icon />
            </Button>
          </Tooltip>
        </header>

        <div
          className="min-h-0 flex-1 overflow-y-auto scrollbar-thin"
          ref={scrollRef}
          onScroll={onScroll}
        >
          <div className="mx-auto h-full w-full max-w-3xl px-4">
            {messages.length === 0 ? (
              <StarterPrompts mode={chat.mode} onPick={send} />
            ) : (
              <div className="space-y-8 py-6" aria-live="polite">
                {messages.map((message) => (
                  <MessageView
                    key={message.id}
                    message={message}
                    onRate={chat.rate}
                    onRetry={
                      message === lastAssistant && !chat.streaming && !message.reportFor
                        ? chat.retry
                        : undefined
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="relative mx-auto w-full max-w-3xl px-4">
          <AnimatePresence>
            {!atBottom && messages.length > 0 && (
              <m.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                className="absolute -top-12 left-1/2 -translate-x-1/2"
              >
                <Button
                  size="icon-sm"
                  variant="outline"
                  className="rounded-full shadow-md"
                  aria-label="Scroll to the latest message"
                  onClick={scrollToBottom}
                >
                  <ArrowDownIcon />
                </Button>
              </m.div>
            )}
          </AnimatePresence>
          <Composer
            streaming={chat.streaming}
            onSend={send}
            onStop={chat.stop}
            tools={<ModeToggle mode={chat.mode} onChange={chat.setMode} />}
          />
        </div>
      </main>

      <Suspense fallback={null}>
        {settingsOpen && <SettingsDialog open onOpenChange={setSettingsOpen} />}
        {openAnalysis && <AnalysisView analysis={openAnalysis} onClose={closeAnalysis} />}
      </Suspense>
    </div>
  );
}

export default function App(props: Props = {}) {
  return (
    <SettingsProvider>
      {/* Motion's features load once here; components use the light `m` elements. */}
      <LazyMotion features={loadMotionFeatures}>
        <ChatScreen {...props} />
      </LazyMotion>
    </SettingsProvider>
  );
}
