"use client";

import ReactMarkdown from "react-markdown";
import { linkTimestamps, seekTarget } from "@/lib/api";
import { useSeek } from "./player";

// a plain click on a timestamp plays the moment in the page's player; ctrl/cmd/middle click still opens YouTube
export function TimestampLink({ href, videoId, className, children }: { href?: string; videoId: string; className?: string; children: React.ReactNode }) {
  const seek = useSeek();
  const sec = seekTarget(href, videoId);
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={className ?? (sec !== null ? "ts" : undefined)}
      onClick={(e) => {
        if (sec === null || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        seek(sec);
      }}
    >
      {children}
    </a>
  );
}

export default function Markdown({ text, videoId }: { text: string; videoId: string }) {
  return (
    <div className="prose">
      <ReactMarkdown
        components={{
          a: ({ href, children }) => (
            <TimestampLink href={href} videoId={videoId}>
              {children}
            </TimestampLink>
          ),
          h2: ({ node, children }) => <h2 id={`l${node?.position?.start.line}`}>{children}</h2>,
        }}
      >
        {linkTimestamps(text, videoId)}
      </ReactMarkdown>
    </div>
  );
}
