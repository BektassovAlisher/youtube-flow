"use client";

import { Children, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { clockSeconds, linkLocators, paragraphTarget, playable, seekTarget, type Material } from "@/lib/api";
import { useLocate } from "./player";

const textOf = (node: ReactNode): string =>
  Children.toArray(node).map((c) => (typeof c === "string" || typeof c === "number" ? String(c) : isValidElement(c) ? textOf((c.props as { children?: ReactNode }).children) : "")).join("");

// A plain click on a place reference opens it right here: a timestamp plays the recording in the page's player,
// a paragraph of a pasted text opens it in the "Текст" tab. Ctrl/cmd/middle click, article paragraphs and
// recordings the page cannot play (links into the original page) open a new tab as usual.
export function TimestampLink({ href, material, className, children }: { href?: string; material: Material; className?: string; children: React.ReactNode }) {
  const locate = useLocate();
  // a timestamp's label is its time: that is how links of recordings from other sites are recognized
  const clock = clockSeconds(textOf(children));
  const sec = material.kind === "youtube" ? seekTarget(href, material.video_id) : playable(material) ? clock : null;
  const paragraph = paragraphTarget(href);
  const place = sec !== null || clock !== null || paragraph !== null || /#:~:text=/.test(href ?? "");
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
          // "**Содержание раздела:**" opens a paragraph as a label, not as a term: set it as one
          strong: ({ children }) => <strong className={textOf(children).trim().endsWith(":") ? "lead" : undefined}>{children}</strong>,
        }}
      >
        {linkLocators(text, material)}
      </ReactMarkdown>
    </div>
  );
}
