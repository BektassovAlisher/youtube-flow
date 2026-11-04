"use client";

import ReactMarkdown from "react-markdown";
import { linkLocators, paragraphTarget, seekTarget, type Material } from "@/lib/api";
import { useLocate } from "./player";

// A plain click on a place reference opens it right here: a timestamp plays the video in the page's player,
// a paragraph of a pasted text opens it in the "Текст" tab. Ctrl/cmd/middle click and article paragraphs
// (links into the original page) open a new tab as usual.
export function TimestampLink({ href, material, className, children }: { href?: string; material: Material; className?: string; children: React.ReactNode }) {
  const locate = useLocate();
  const sec = seekTarget(href, material.video_id);
  const paragraph = paragraphTarget(href);
  const place = sec !== null || paragraph !== null || /#:~:text=/.test(href ?? "");
  return (
    <a
      href={href}
      target={paragraph !== null ? undefined : "_blank"}
      rel="noreferrer"
      className={className ?? (place ? "ts" : undefined)}
      onClick={(e) => {
        if ((sec === null && paragraph === null) || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        if (sec !== null) locate.seek(sec);
        else locate.paragraph(paragraph!);
      }}
    >
      {children}
    </a>
  );
}

export default function Markdown({ text, material }: { text: string; material: Material }) {
  return (
    <div className="prose">
      <ReactMarkdown
        components={{
          a: ({ href, children }) => (
            <TimestampLink href={href} material={material}>
              {children}
            </TimestampLink>
          ),
          h2: ({ node, children }) => <h2 id={`l${node?.position?.start.line}`}>{children}</h2>,
        }}
      >
        {linkLocators(text, material)}
      </ReactMarkdown>
    </div>
  );
}
