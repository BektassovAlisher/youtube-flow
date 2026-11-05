import Link from "next/link";
import { addedOn, CATEGORY, cover, kindLabel, lengthLabel, plural, siteOf, type VideoListItem } from "@/lib/api";
import { serverApi } from "@/lib/server-api";
import CoverImage from "../cover-image";
import Eq from "../eq";

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
  const count = `${total} ${plural(total, "материал", "материала", "материалов")}`;

  return (
    <>
      <div className="band lib-head">
        <div>
          <h1>Библиотека</h1>
          {videos && <p className="meta">{q ? `По запросу «${q}»: ${count}` : count}</p>}
        </div>
        <form className="search" action="/library" role="search">
          <label className="field-label" htmlFor="library-q">Поиск по названию, каналу или сайту</label>
          <input className="field" id="library-q" type="search" name="q" defaultValue={q} />
        </form>
      </div>

      {!videos && <p className="error">Сервер API недоступен. Библиотека появится, когда он запустится.</p>}

      {videos?.length === 0 && (
        <p className="empty">
          {q ? (
            <>
              Ничего не нашлось. <Link href="/library">Показать всё</Link>
            </>
          ) : (
            <>
              Здесь будут все обработанные материалы. <Link href="/">Сделайте первый конспект</Link>
            </>
          )}
        </p>
      )}

      {!!videos?.length && (
        <ul className="rows">
          {videos.map((v) => {
            const meta = [kindLabel(v), v.channel || (v.kind !== "youtube" && v.kind !== "text" && siteOf(v.url)), v.language?.toUpperCase(), lengthLabel(v), CATEGORY[v.category ?? ""]]
              .filter((t, i, all): t is string => !!t && t !== CATEGORY.unknown && all.indexOf(t) === i);
            return (
              <li key={v.video_id}>
                <Link href={`/videos/${v.video_id}`} className="row">
                  <CoverImage src={cover(v)} label={v.kind === "article" ? v.channel || siteOf(v.url) : v.kind === "media" ? siteOf(v.url) : kindLabel(v)} />
                  <span>
                    <span className="row-title">{v.title ?? v.video_id}</span>
                    <span className="row-meta">{meta.join(" · ")}</span>
                  </span>
                  <span className="row-side">
                    {v.status === "processing" ? (
                      <span className="state">
                        <Eq /> Обрабатывается
                      </span>
                    ) : (
                      addedOn(v.created_at)
                    )}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      {pages > 1 && (
        <nav className="pager" aria-label="Страницы">
          {page > 1 ? <Link className="btn small" href={link(page - 1)}>← Назад</Link> : <span />}
          <span className="muted num">
            {page} из {pages}
          </span>
          {page < pages ? <Link className="btn small" href={link(page + 1)}>Дальше →</Link> : <span />}
        </nav>
      )}
    </>
  );
}
