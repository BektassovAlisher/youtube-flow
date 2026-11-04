"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { thumb } from "@/lib/api";

// Timestamps in the summary and answers play the video right here instead of opening YouTube in a new tab.
export const SeekContext = createContext<(sec: number) => void>(() => {});
export const useSeek = () => useContext(SeekContext);

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
            <img className="thumb" src={thumb(id, "hqdefault")} alt="" />
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
