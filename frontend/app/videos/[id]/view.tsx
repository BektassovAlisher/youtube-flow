"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { api, CATEGORY, isAudio, isMediaFile, kindLabel, lengthLabel, notEducational, siteOf, stagesFor, type Job, type Kind, type VideoInfo } from "@/lib/api";
import CoverImage from "../../cover-image";
import Eq from "../../eq";
import ErrorText from "../../error-text";
import { useLive } from "./live";
import { Audio, Questions, Quiz, Recommendations, Script, SourceText, splitQuiz, Summary } from "./panels";
import { LocateContext, MediaPlayer, Player, type PlayAt } from "./player";

const TABS = [
  ["summary", "Конспект"],
  ["text", "Текст"],
  ["quiz", "Проверь себя"],
  ["script", "Сценарий"],
  ["audio", "Аудио"],
  ["recs", "Рекомендации"],
  ["qa", "Вопросы"],
] as const;
type Tab = (typeof TABS)[number][0];

const isTab = (t: string | undefined): t is Tab => TABS.some(([k]) => k === t);

export default function VideoView({ id, initial, apiDown, initialTab }: { id: string; initial: VideoInfo | null; apiDown: boolean; initialTab?: string }) {
  const router = useRouter();
  const { video, setVideo, jobs, partial, failure, follow } = useLive(id, initial);
  const [tab, setTab] = useState<Tab>(isTab(initialTab) ? initialTab : "summary");
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set([tab]));
  const [at, setAt] = useState<PlayAt>(null);
  const [focus, setFocus] = useState<{ n: number; key: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // panels stay mounted once opened, so chat history, opened answers and the player survive tab switches
  const open = useCallback((t: Tab) => {
    setTab(t);
    setVisited((v) => (v.has(t) ? v : new Set(v).add(t)));
    window.history.replaceState(null, "", t === "summary" ? window.location.pathname : `?tab=${t}`);
  }, []);
  const locate = useMemo(
    () => ({
      seek: (sec: number) => setAt((p) => ({ sec, n: (p?.n ?? 0) + 1 })),
      paragraph: (n: number) => {
        open("text");
        setFocus((f) => ({ n, key: (f?.key ?? 0) + 1 }));
      },
    }),
    [open],
  );

  // starts a background job, then follows its progress through the events stream
  async function run(request: () => Promise<VideoInfo | unknown>) {
    setBusy(true);
    setError(null);
    try {
      const result = await request();
      if (result && typeof result === "object" && "video_id" in result && "status" in result) setVideo(result as VideoInfo);
      follow();
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }
  const process = (force = false) =>
    run(() => api<VideoInfo>("videos", { method: "POST", body: JSON.stringify(video?.kind === "article" ? { url: video.url, force } : { url: id, force }) }));
  // continues from the last saved step, whatever the kind of material
  const resume = () => run(() => api<VideoInfo>(`videos/${id}/resume`, { method: "POST" }));
  const regenerate = (part: "summary" | "script") =>
    run(() => api<VideoInfo>(`videos/${id}/regenerate`, { method: "POST", body: JSON.stringify({ part }) }));
  const createAudio = () => run(() => api(`videos/${id}/audio`, { method: "POST" }));

  async function remove() {
    if (!confirm("Удалить материал и всё, что по нему создано?")) return;
    try {
      await api(`videos/${id}`, { method: "DELETE" });
      router.push("/library");
    } catch (e) {
      setError(e as Error);
    }
  }

  const back = (
    <Link href="/library" className="back">
      ← Библиотека
    </Link>
  );

  if (!video)
    return (
      <>
        {back}
        <div className="notice">
          {apiDown ? (
            <>
              <h3>Сервер API недоступен</h3>
              <p>Обновите страницу чуть позже.</p>
            </>
          ) : (
            <>
              <h3>Материал не найден</h3>
              <p>Его ещё не обрабатывали или удалили.</p>
              {/^[\w-]{11}$/.test(id) && (
                <div className="actions">
                  <button className="btn small" onClick={() => process()} disabled={busy}>Обработать это видео</button>
                </div>
              )}
            </>
          )}
          {error && <ErrorText error={error} />}
        </div>
      </>
    );

  const kind: Kind = video.kind ?? "youtube";
  const processJob = jobs.find((j) => j.kind === "process");
  const audioJob = jobs.find((j) => j.kind === "audio");
  const quiz = splitQuiz(video.summary).questions;
  // the summary is being streamed: show it in its final place instead of under the progress list
  const live = !video.summary && !!partial && video.status !== "failed" && failure?.kind !== "process";
  const shown: Tab = live ? "summary" : tab;
  const tabs = TABS.filter(([k]) => (k !== "quiz" || quiz.length > 0) && (k !== "text" || kind === "text"));
  const meta = [kind !== "youtube" && kindLabel(video), kind === "media" && siteOf(video.url), CATEGORY[video.category ?? ""], video.language?.toUpperCase(), video.channel, lengthLabel(video)]
    .filter((x, i, all) => x && x !== CATEGORY.unknown && all.indexOf(x) === i)
    .join(" · ");

  // the right column only when there is something to play or a real cover; a pasted text gets the full width
  const media =
    kind === "youtube" ? (
      <Player id={id} at={at} onPlay={locate.seek} onClose={() => setAt(null)} />
    ) : kind === "media" && isMediaFile(video.url) ? (
      <MediaPlayer url={video.url} audio={isAudio(video.url)} at={at} title={video.title ?? ""} />
    ) : video.image_url ? (
      <Cover video={video} />
    ) : null;

  return (
    <LocateContext.Provider value={locate}>
      <div className="band cover">
        {back}

        <div className={media ? "vhead" : "vhead solo"}>
          <div>
            {meta && <p className="meta">{meta}</p>}
            <h1>{video.title ?? id}</h1>
            <div className="actions">
              {kind === "youtube" && (
                <a className="btn small" href={`https://www.youtube.com/watch?v=${id}`} target="_blank" rel="noreferrer">
                  Открыть на YouTube ↗
                </a>
              )}
              {(kind === "article" || kind === "media") && (
                <a className="btn small" href={video.url} target="_blank" rel="noreferrer">
                  {kind === "article" ? "Открыть статью ↗" : "Открыть оригинал ↗"}
                </a>
              )}
              <button className="btn small danger" onClick={remove} disabled={jobs.length > 0}>Удалить</button>
            </div>
            {error && <ErrorText error={error} />}
          </div>
          {media && <div className="media">{media}</div>}
        </div>
      </div>

      {video.status === "rejected" ? (
        <div className="notice" role="status">
          <h3>{notEducational(kind)}</h3>
          <p>Категория: {CATEGORY[video.classification?.category ?? "unknown"] ?? video.classification?.category}</p>
          {video.classification?.reason && <p>{video.classification.reason}</p>}
          <div className="actions">
            <button className="btn small" onClick={() => process(true)} disabled={busy}>Всё равно обработать</button>
          </div>
        </div>
      ) : !video.summary && !live ? (
        <Progress
          kind={kind}
          job={processJob}
          video={video}
          error={video.status === "failed" || failure?.kind === "process" ? (failure?.message ?? video.error) : null}
          stuck={!processJob && video.status === "processing"}
          busy={busy}
          onResume={resume}
        />
      ) : (
        <>
          {/* while the summary is written it already sits where the finished one will be: same tabs, same columns,
              same margin for the timestamps. The status lives in the tab row, so it takes no height of its own and
              nothing moves when it goes away. */}
          <div className="tabs" role="tablist" aria-label="Разделы материала">
            {tabs.map(([k, label]) => (
              <button key={k} role="tab" className="tab" aria-selected={shown === k} disabled={live && k !== "summary"} onClick={() => open(k)}>
                {label}
              </button>
            ))}
            {processJob && (
              <span className="tabs-status" role="status">
                <Eq /> {live ? "Пишу конспект…" : "Пишу сценарий подкаста…"}
              </span>
            )}
          </div>
          {tabs.map(([k]) =>
            visited.has(k) || k === shown ? (
              <section key={k} className="panel" role="tabpanel" hidden={shown !== k}>
                {k === "summary" && (
                  <Summary video={live ? { ...video, summary: partial } : video} live={live} busy={busy || !!processJob} onRegenerate={() => regenerate("summary")} />
                )}
                {k === "text" && <SourceText id={id} focus={focus} />}
                {k === "quiz" && <Quiz material={video} questions={quiz} />}
                {k === "script" && (
                  <Script video={video} job={processJob} failure={failure} busy={busy} onCreate={resume} onRegenerate={() => regenerate("script")} />
                )}
                {k === "audio" && <Audio video={video} job={audioJob} failure={failure} busy={busy} onCreate={createAudio} />}
                {k === "recs" && <Recommendations id={id} initial={video.recommendation} />}
                {k === "qa" && <Questions material={video} />}
              </section>
            ) : null,
          )}
        </>
      )}
    </LocateContext.Provider>
  );
}

// an article's or a recording's cover, linking to the original (the site's name if the picture fails to load)
function Cover({ video }: { video: VideoInfo }) {
  const label = video.kind === "media" ? siteOf(video.url) : video.channel || siteOf(video.url);
  return (
    <a className="cover" href={video.url} target="_blank" rel="noreferrer" aria-label="Открыть оригинал">
      <CoverImage src={video.image_url} label={label} lazy={false} />
    </a>
  );
}

function Progress({ kind, job, error, stuck, busy, onResume }: {
  kind: Kind; job?: Job; video: VideoInfo; error: string | null; stuck: boolean; busy: boolean; onResume: () => void;
}) {
  const stages = stagesFor(kind);
  const current = stages.findIndex(([key]) => key === job?.stage);
  const active = job ? Math.max(current, 0) : -1;
  return (
    <section className="progress">
      {error ? (
        <div className="notice" role="alert">
          <h3>Не получилось обработать {{ youtube: "видео", media: "запись", article: "статью", text: "текст" }[kind]}</h3>
          <p>{error}</p>
          <div className="actions">
            <button className="btn small" onClick={onResume} disabled={busy}>Попробовать ещё раз</button>
          </div>
        </div>
      ) : (
        <>
          <ol className="stages" aria-live="polite">
            {stages.map(([key, label], i) => (
              <li key={key} data-state={i < active ? "done" : i === active ? "active" : undefined}>
                <span className="stage-mark">{i < active ? "✓" : i === active ? <Eq /> : ""}</span>
                {label}
              </li>
            ))}
          </ol>
          <p className="stages-hint muted">
            {job?.status === "queued"
              ? "В очереди: сервер сейчас обрабатывает другие материалы."
              : "Страницу можно закрыть: обработка продолжится на сервере, а конспект появится здесь."}
          </p>
          {stuck && (
            <div className="notice">
              <p>Обработка не идёт. Возможно, сервер перезапускался.</p>
              <div className="actions">
                <button className="btn small" onClick={onResume} disabled={busy}>Продолжить</button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
