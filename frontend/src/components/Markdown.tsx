import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "../lib/utils";

// Raw HTML in model output is not rendered (react-markdown's default), and links open
// in a new tab so the conversation stays in place.
const components: Components = {
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-border scrollbar-thin">
      <table className="my-0">{children}</table>
    </div>
  ),
};

interface Props {
  text: string;
  className?: string;
  /** Show a blinking caret after the last block while the text streams. */
  streaming?: boolean;
}

export default function Markdown({ text, className, streaming = false }: Props) {
  return (
    <div
      className={cn(
        "prose prose-sm max-w-none text-foreground dark:prose-invert sm:prose-base",
        "prose-headings:font-semibold prose-headings:tracking-tight prose-a:text-primary prose-a:no-underline hover:prose-a:underline",
        "prose-strong:text-foreground prose-code:rounded prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none",
        "prose-pre:bg-muted prose-pre:text-foreground prose-th:bg-muted/60 prose-th:px-3 prose-td:px-3 prose-table:text-sm",
        "prose-p:leading-relaxed prose-li:my-0.5",
        streaming && "streaming-caret",
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
