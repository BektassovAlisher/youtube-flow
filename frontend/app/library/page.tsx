import Link from "next/link";
import type { CSSProperties } from "react";
import { addedOn, CATEGORY, cover, KIND_LABEL, lengthLabel, siteOf, type VideoListItem } from "@/lib/api";
import { serverApi } from "@/lib/server-api";
import CoverImage from "../cover-image";

const PAGE = 24;

export default async function LibraryPage({ searchParams }: PageProps<"/library">) {
  const params = await searchParams;
  const q = typeof params.q === "string" ? params.q.trim() : "";
  const page = Math.max(1, Number(params.page) || 1);
  const query = new URLSearchParams({ limit: String(PAGE), offset: String((page - 1) * PAGE), ...(q && { q }) });
  const { data: videos, headers } = await serverApi<VideoListItem[]>(`videos?${query}`);
  const total = Number(headers?.get("x-total-count") ?? videos?.length ?? 0);
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const link = (p: number) => `/library?${new URLSearchParams({ ...(q && { q }), ...(p > 1 && { page: String(p) }) })}`;

  return (
    <>
      <div className="bar rise">
        <div>
          {videos && <p className="eyebrow">{q ? `Найдено: ${total}` : `Материалов: ${total}`}</p>}
          <h1 className="section-title">Библиотека</h1>
        </div>
        <form className="search" action="/library">
          <input className="field" type="search" name="q" defaultValue={q} placeholder="Название, канал или сайт" aria-label="Поиск" />
        </form>
      </div>

      {!videos && <p className="error">Сервер API недоступен — библиотека появится, когда он запустится.</p>}

      {videos?.length === 0 && (
        <p className="empty fade">
          {q ? (
            <>
              Ничего не нашлось. <Link href="/library">Показать всё</Link>
            </>
          ) : (
            <>
              Пока пусто. <Link href="/">Создайте первый конспект →</Link>
            </>
          )}
        </p>
      )}

      <ul className="grid">
        {videos?.map((v, i) => {
          const tags = [v.kind !== "youtube" && KIND_LABEL[v.kind], v.language?.toUpperCase(), lengthLabel(v), CATEGORY[v.category ?? ""]]
            .filter((t): t is string => !!t && t !== CATEGORY.unknown);
          return (
            <li key={v.video_id} className="rise" style={{ "--d": Math.min(i, 12) } as CSSProperties}>
              <Link href={`/videos/${v.video_id}`} className="card">
                <div className="media">
                  <CoverImage src={cover(v)} label={v.kind === "article" ? v.channel || siteOf(v.url) : KIND_LABEL[v.kind]} />
                  {v.status === "processing" && <span className="badge">Обрабатывается</span>}
                </div>
                <div className="card-body">
                  <div className="card-title">{v.title ?? v.video_id}</div>
                  {v.channel && <div className="date">{v.channel}</div>}
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

      {pages > 1 && (
        <nav className="pager" aria-label="Страницы">
          {page > 1 ? <Link className="btn small" href={link(page - 1)}>← Назад</Link> : <span />}
          <span className="muted">
            {page} из {pages}
          </span>
          {page < pages ? <Link className="btn small" href={link(page + 1)}>Дальше →</Link> : <span />}
        </nav>
      )}
    </>
  );
}
