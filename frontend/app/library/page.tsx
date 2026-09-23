import Link from "next/link";
import type { CSSProperties } from "react";
import { addedOn, CATEGORY, minutes, thumb, type VideoListItem } from "@/lib/api";
import { serverApi } from "@/lib/server-api";

export default async function LibraryPage() {
  const videos = await serverApi<VideoListItem[]>("videos");
  const error = videos ? null : "API недоступен";

  return (
    <>
      <div className="bar rise">
        <div>
          {videos && <p className="eyebrow">{videos.length} видео</p>}
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
