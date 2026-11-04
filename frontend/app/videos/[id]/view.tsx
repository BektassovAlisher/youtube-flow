"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState, type CSSProperties } from "react";
import { api, CATEGORY, STAGES, type Job, type VideoInfo } from "@/lib/api";
import Eq from "../../eq";
import ErrorText from "../../error-text";
import { useLive } from "./live";
import Markdown from "./markdown";
import { Audio, Questions, Quiz, Recommendations, Script, splitQuiz, Summary } from "./panels";
import { Player, SeekContext, type PlayAt } from "./player";

const TABS = [
  ["summary", "Конспект"],
  ["quiz", "Проверь себя"],
  ["script", "Сценарий"],
  ["audio", "Аудио"],
  ["recs", "Рекомендации"],
  ["qa", "Вопросы"],
] as const;
type Tab = (typeof TABS)[number][0];

const d = (n: number) => ({ "--d": n }) as CSSProperties;
const isTab = (t: string | undefined): t is Tab => TABS.some(([k]) => k === t);

export default function VideoView({ id, initial, apiDown, initialTab }: { id: string; initial: VideoInfo | null; apiDown: boolean; initialTab?: string }) {
  const router = useRouter();
  const { video, setVideo, jobs, partial, failure, follow } = useLive(id, initial);
  const [tab, setTab] = useState<Tab>(isTab(initialTab) ? initialTab : "summary");
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set([tab]));
  const [at, setAt] = useState<PlayAt>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const seek = useCallback((sec: number) => setAt((p) => ({ sec, n: (p?.n ?? 0) + 1 })), []);

  // panels stay mounted once opened, so chat history, opened answers and the player survive tab switches
  function open(t: Tab) {
    setTab(t);
    setVisited((v) => (v.has(t) ? v : new Set(v).add(t)));
    window.history.replaceState(null, "", t === "summary" ? window.location.pathname : `?tab=${t}`);
  }

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
  const process = (force = false) => run(() => api<VideoInfo>("videos", { method: "POST", body: JSON.stringify({ video_url: id, force }) }));
  const regenerate = (part: "summary" | "script") =>
    run(() => api<VideoInfo>(`videos/${id}/regenerate`, { method: "POST", body: JSON.stringify({ part }) }));
  const createAudio = () => run(() => api(`videos/${id}/audio`, { method: "POST" }));

  async function remove() {
    if (!confirm("Удалить видео и все материалы по нему?")) return;
    try {
      await api(`videos/${id}`, { method: "DELETE" });
      router.push("/library");
    } catch (e) {
      setError(e as Error);
    }
  }

  const back = (
    <Link href="/library" className="back eyebrow">
      <span>←</span> Библиотека
    </Link>
  );

  if (!video)
    return (
      <>
        {back}
        <div className="notice fade">
          {apiDown ? (
            <>
              <h3>Сервер API недоступен</h3>
              <p>Обновите страницу чуть позже.</p>
            </>
          ) : (
            <>
              <h3>Видео не найдено</h3>
              <p>Его ещё не обрабатывали или удалили.</p>
              {/^[\w-]{11}$/.test(id) && (
                <div className="actions notice-actions">
                  <button className="btn small" onClick={() => process()} disabled={busy}>Обработать это видео</button>
                </div>
              )}
            </>
          )}
          {error && <ErrorText error={error} />}
        </div>
      </>
    );

  const processJob = jobs.find((j) => j.kind === "process");
  const audioJob = jobs.find((j) => j.kind === "audio");
  const quiz = splitQuiz(video.summary).questions;
  const tabs = TABS.filter(([k]) => k !== "quiz" || quiz.length > 0);
  const meta = [CATEGORY[video.category ?? ""], video.language?.toUpperCase(), video.channel].filter(Boolean).join(" · ");

  return (
    <SeekContext.Provider value={seek}>
      {back}

      <div className="vhead">
        <div>
          {meta && <p className="eyebrow rise">{meta}</p>}
          <h1 className="rise" style={d(1)}>{video.title ?? id}</h1>
          <div className="actions rise" style={d(2)}>
            <a className="btn small" href={`https://www.youtube.com/watch?v=${id}`} target="_blank" rel="noreferrer">
              Открыть на YouTube ↗
            </a>
            <button className="btn small danger" onClick={remove} disabled={jobs.length > 0}>Удалить</button>
          </div>
          {error && <ErrorText error={error} />}
        </div>
        <div className="media rise" style={d(1)}>
          <Player id={id} at={at} onPlay={seek} onClose={() => setAt(null)} />
        </div>
      </div>

      {video.status === "rejected" ? (
        <div className="notice fade" role="status">
          <h3>Похоже, это не обучающее видео</h3>
          <p>Категория: {CATEGORY[video.classification?.category ?? "unknown"] ?? video.classification?.category}</p>
          {video.classification?.reason && <p>{video.classification.reason}</p>}
          <div className="actions notice-actions">
            <button className="btn small" onClick={() => process(true)} disabled={busy}>Всё равно обработать</button>
          </div>
        </div>
      ) : !video.summary ? (
        <Progress
          job={processJob}
          partial={partial}
          videoId={id}
          error={video.status === "failed" || failure?.kind === "process" ? (failure?.message ?? video.error) : null}
          stuck={!processJob && video.status === "processing"}
          busy={busy}
          onResume={() => process()}
        />
      ) : (
        <>
          {processJob && processJob.stage !== "summary" && (
            <p className="banner inline fade">
              <Eq /> Конспект готов. Сценарий подкаста ещё пишется — он появится во вкладке «Сценарий».
            </p>
          )}
          <div className="tabs rise" style={d(3)} role="tablist">
            {tabs.map(([k, label]) => (
              <button key={k} role="tab" className="tab" aria-selected={tab === k} onClick={() => open(k)}>
                {label}
              </button>
            ))}
          </div>
          {tabs.map(([k]) =>
            visited.has(k) ? (
              <section key={k} className="panel fade" role="tabpanel" hidden={tab !== k}>
                {k === "summary" && <Summary video={video} busy={busy || !!processJob} onRegenerate={() => regenerate("summary")} />}
                {k === "quiz" && <Quiz id={id} questions={quiz} />}
                {k === "script" && (
                  <Script video={video} job={processJob} failure={failure} busy={busy} onCreate={() => process()} onRegenerate={() => regenerate("script")} />
                )}
                {k === "audio" && <Audio video={video} job={audioJob} failure={failure} busy={busy} onCreate={createAudio} />}
                {k === "recs" && <Recommendations id={id} initial={video.recommendation} />}
                {k === "qa" && <Questions id={id} />}
              </section>
            ) : null,
          )}
        </>
      )}
    </SeekContext.Provider>
  );
}

function Progress({ job, partial, videoId, error, stuck, busy, onResume }: {
  job?: Job; partial: string; videoId: string; error: string | null; stuck: boolean; busy: boolean; onResume: () => void;
}) {
  const current = STAGES.findIndex(([key]) => key === job?.stage);
  const active = job ? Math.max(current, 0) : -1;
  return (
    <section className="progress">
      {error ? (
        <div className="notice fade" role="alert">
          <h3>Не получилось обработать видео</h3>
          <p>{error}</p>
          <div className="actions notice-actions">
            <button className="btn small" onClick={onResume} disabled={busy}>Попробовать ещё раз</button>
          </div>
        </div>
      ) : (
        <>
          <ol className="stages fade" aria-live="polite">
            {STAGES.map(([key, label], i) => (
              <li key={key} data-state={i < active ? "done" : i === active ? "active" : undefined}>
                <span className="stage-mark">{i < active ? "✓" : i === active ? <Eq /> : ""}</span>
                {label}
              </li>
            ))}
          </ol>
          <p className="stages-hint muted">
            {job?.status === "queued"
              ? "Видео в очереди: сервер сейчас обрабатывает другие."
              : "Страницу можно закрыть — обработка продолжится на сервере, а конспект появится здесь."}
          </p>
          {stuck && (
            <div className="notice fade">
              <p>Обработка не идёт — возможно, сервер перезапускался.</p>
              <div className="actions notice-actions">
                <button className="btn small" onClick={onResume} disabled={busy}>Продолжить</button>
              </div>
            </div>
          )}
        </>
      )}
      {partial && !error && (
        <div className="live-summary fade">
          <p className="eyebrow">Конспект пишется прямо сейчас</p>
          <Markdown text={partial} videoId={videoId} />
          <span className="live-caret" aria-hidden />
        </div>
      )}
    </section>
  );
}
