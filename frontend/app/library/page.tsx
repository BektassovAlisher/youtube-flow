"use client";

import Link from "next/link";
import { useEffect, useState, type CSSProperties } from "react";
import { addedOn, api, CATEGORY, minutes, thumb, type VideoListItem } from "@/lib/api";

export default function LibraryPage() {
  const [videos, setVideos] = useState<VideoListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<VideoListItem[]>("videos")
      .then(setVideos)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <div className="bar rise">
        <div>
          <p className="eyebrow">{videos ? `${videos.length} видео` : "Загрузка"}</p>
          <h1 className="section-title">Библиотека</h1>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {videos?.length === 0 && (
        <p className="empty fade">
          Пока пусто. <Link href="/">Создайте первый конспект →</Link>
        </p>
      )}

      <ul className="grid">
        {!videos && !error && [0, 1, 2].map((i) => <li key={i} className="skeleton" />)}
        {videos?.map((v, i) => {
          const tags = [v.language?.toUpperCase(), minutes(v.duration_sec), CATEGORY[v.category ?? ""]].filter(Boolean);
          return (
            <li key={v.video_id} className="rise" style={{ "--d": i } as CSSProperties}>
              <Link href={`/videos/${v.video_id}`} className="card">
                <div className="media">
                  <img className="thumb" src={thumb(v.video_id)} alt="" loading="lazy" />
                </div>
                <div className="card-body">
                  <div className="card-title">{v.title ?? v.video_id}</div>
                  <div className="tags">
                    {tags.map((t) => (
                      <span key={t} className="tag">{t}</span>
                    ))}
                  </div>
                  <div className="card-foot">
                    <span className="date">{addedOn(v.created_at)}</span>
                    <span className="arrow">→</span>
                  </div>
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </>
  );
}
