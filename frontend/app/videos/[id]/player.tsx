"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { thumb } from "@/lib/api";
import CoverImage from "../../cover-image";

// Places in the summary and answers open on the page itself: a timestamp plays the video here instead of a
// new YouTube tab, a paragraph number of a pasted text opens it in the "Текст" tab.
export type Locate = { seek: (sec: number) => void; paragraph: (n: number) => void };
export const LocateContext = createContext<Locate>({ seek: () => {}, paragraph: () => {} });
export const useLocate = () => useContext(LocateContext);

export type PlayAt = { sec: number; n: number } | null; // n changes on every seek, even to the same second

export function Player({ id, at, onPlay, onClose }: { id: string; at: PlayAt; onPlay: (sec: number) => void; onClose: () => void }) {
  const slot = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(true);

  // while playing, the player keeps floating in a corner when its place scrolls out of view;
  // it is the same element (only CSS changes), so playback does not restart
  useEffect(() => {
    const el = slot.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold: 0.25 });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const floating = at !== null && !inView;
  return (
    <div className="player-slot" ref={slot}>
      <div className="player" data-floating={floating || undefined}>
        {at === null ? (
          <button className="player-poster" onClick={() => onPlay(0)} aria-label="Смотреть видео здесь">
            <CoverImage src={thumb(id, "hqdefault")} label="YouTube" lazy={false} />
            <span className="play-btn" aria-hidden>▶</span>
          </button>
        ) : (
          <iframe
            key={at.n}
            src={`https://www.youtube-nocookie.com/embed/${id}?start=${at.sec}&autoplay=1&rel=0`}
            title="Видео"
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
          />
        )}
        {floating && (
          <button className="player-close" onClick={onClose} aria-label="Закрыть видео">
            ✕
          </button>
        )}
      </div>
    </div>
  );
}

// media files by direct link (a podcast episode, a lecture recording): the browser plays them itself
export function MediaPlayer({ url, audio, at, title }: { url: string; audio: boolean; at: PlayAt; title: string }) {
  const el = useRef<HTMLMediaElement | null>(null);
  useEffect(() => {
    if (!at || !el.current) return;
    el.current.currentTime = at.sec;
    el.current.play().catch(() => {}); // autoplay can be refused; the position is set anyway
    if (audio) el.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [at, audio]);
  return audio ? (
    <div className="media-file">
      <span className="media-file-title">{title}</span>
      <audio ref={(node) => void (el.current = node)} controls preload="metadata" src={url} />
    </div>
  ) : (
    <video ref={(node) => void (el.current = node)} className="media-video" controls preload="metadata" src={url} />
  );
}
