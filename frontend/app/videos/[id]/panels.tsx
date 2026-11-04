"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { api, ApiError, askStream, type Answer, type Job, type Recs, type VideoInfo } from "@/lib/api";
import Eq from "../../eq";
import ErrorText from "../../error-text";
import type { Failure } from "./live";
import Markdown, { TimestampLink } from "./markdown";

const idx = (i: number) => ({ "--i": Math.min(i, 20) }) as CSSProperties;

// The summary ends with "## Вопросы для самопроверки" + a numbered list: cut it out and render it as quiz cards.
export function splitQuiz(md: string) {
  const lines = md.split("\n");
  const start = lines.findIndex((l) => /^##\s*Вопросы для самопроверки/i.test(l));
  if (start < 0) return { body: md, questions: [] as string[] };
  let end = lines.findIndex((l, i) => i > start && /^#{1,2}\s/.test(l));
  if (end < 0) end = lines.length;
  const questions = lines
    .slice(start + 1, end)
    .map((l) => l.match(/^\s*(?:[-*]|\d+[.)])\s+(.+)/)?.[1].replace(/\*\*/g, "").trim())
    .filter((q): q is string => !!q);
  if (!questions.length) return { body: md, questions };
  return { body: [...lines.slice(0, start), ...lines.slice(end)].join("\n"), questions };
}

// "## [04:12] Title" -> { id: "l<line>", ts: "04:12", title }; ids match the h2 ids set in <Markdown>
function toc(md: string) {
  return md.split("\n").flatMap((l, i) => {
    const m = l.match(/^##\s+(?:\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*)?(.+)/);
    return m ? [{ id: `l${i + 1}`, ts: m[1], title: m[2].replace(/\*\*/g, "") }] : [];
  });
}

function download(name: string, text: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export function Summary({ video, onRegenerate, busy }: { video: VideoInfo; onRegenerate: () => void; busy: boolean }) {
  const { body } = splitQuiz(video.summary);
  const sections = toc(body);
  return (
    <div className="summary">
      <div>
        {video.keywords.length > 0 && (
          <div className="keywords">
            <p className="eyebrow">Ключевые термины</p>
            <div className="chips">
              {video.keywords.map((k) => (
                <span key={k} className="chip">{k}</span>
              ))}
            </div>
          </div>
        )}
        <Markdown text={body} videoId={video.video_id} />
        <div className="toolbar">
          <button className="btn small" onClick={() => download(`${video.title ?? video.video_id}.md`, `# ${video.title ?? video.video_id}\n\n${video.summary}`)}>
            Скачать .md ↓
          </button>
          <button
            className="btn small"
            disabled={busy}
            onClick={() => confirm("Написать конспект заново? Термины, сценарий, аудио и сохранённые ответы тоже обновятся.") && onRegenerate()}
          >
            Пересоздать конспект
          </button>
        </div>
      </div>
      {sections.length > 1 && (
        <nav className="toc" aria-label="Содержание">
          <p className="eyebrow">Содержание</p>
          {sections.map((t) => (
            <a key={t.id} href={`#${t.id}`}>
              {t.ts && <span className="t">{t.ts}</span>}
              {t.title}
            </a>
          ))}
        </nav>
      )}
    </div>
  );
}

// streams an answer into `update`, re-rendering at most once per frame
async function streamAnswer(id: string, q: string, history: { q: string; a: string }[], update: (a: Answer) => void) {
  let answer = "";
  let sources: Answer["sources"] = [];
  let frame = 0;
  const push = () => {
    frame = 0;
    update({ answer, sources });
  };
  await askStream(id, q, history, (e) => {
    if (e.type === "error") throw new ApiError(e.message, 500);
    if (e.type === "sources") sources = e.sources;
    if (e.type === "token") answer += e.text;
    if (!frame) frame = requestAnimationFrame(push);
  });
  cancelAnimationFrame(frame);
  push();
}

function AnswerView({ a, id, live }: { a: Answer; id: string; live?: boolean }) {
  return (
    <div className="fade">
      {a.answer ? <Markdown text={a.answer} videoId={id} /> : <p className="inline accent"><Eq /> Ищу ответ в транскрипте…</p>}
      {live && a.answer && <span className="live-caret" aria-hidden />}
      {a.sources.length > 0 && (
        <div className="sources">
          <span className="eyebrow">Фрагменты:</span>
          {a.sources.map((s, j) => (
            <TimestampLink key={j} href={s.url} videoId={id} className="ts">
              {s.timestamp}
            </TimestampLink>
          ))}
        </div>
      )}
    </div>
  );
}

export function Quiz({ id, questions }: { id: string; questions: string[] }) {
  return (
    <section className="quiz">
      <p className="muted">Сначала ответьте сами, потом откройте ответ — он строится по транскрипту видео.</p>
      <ol className="quiz-list">
        {questions.map((q, i) => (
          <QuizCard key={q} id={id} n={i + 1} q={q} />
        ))}
      </ol>
    </section>
  );
}

function QuizCard({ id, n, q }: { id: string; n: number; q: string }) {
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function reveal() {
    setLive(true);
    setError(null);
    setAnswer({ answer: "", sources: [] });
    try {
      await streamAnswer(id, q, [], setAnswer); // cached on the server: the next reveal is instant and free
    } catch (e) {
      setAnswer(null);
      setError(e as Error);
    } finally {
      setLive(false);
    }
  }

  return (
    <li className="quiz-card" data-open={answer ? "" : undefined}>
      <span className="eyebrow">Вопрос {n}</span>
      <p className="quiz-q">{q}</p>
      {answer ? (
        <AnswerView a={answer} id={id} live={live} />
      ) : (
        <button className="btn small" onClick={reveal}>Показать ответ</button>
      )}
      {error && <ErrorText error={error} />}
    </li>
  );
}

export function Script({ video, job, failure, busy, onCreate, onRegenerate }: {
  video: VideoInfo; job?: Job; failure: Failure | null; busy: boolean; onCreate: () => void; onRegenerate: () => void;
}) {
  if (job) {
    return (
      <div className="box">
        <p className="inline accent"><Eq /> {job.status === "queued" ? "Сценарий в очереди…" : "Пишу сценарий — редактор проверяет каждую версию…"}</p>
        <p className="muted">Конспект уже готов, сценарий появится здесь сам.</p>
      </div>
    );
  }
  const lines = video.podcast_script
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const i = l.indexOf(":");
      const name = i > 0 ? l.slice(0, i).replace(/\*/g, "").trim() : "";
      return name && name.length <= 20 ? { name, text: l.slice(i + 1).replace(/^[\s*]+/, "") } : { name: "", text: l };
    });
  if (!lines.length) {
    const message = failure?.kind === "process" ? failure.message : video.error;
    return (
      <div className="box">
        {message ? <ErrorText error={message} /> : <p>Сценария подкаста пока нет.</p>}
        <button className="btn primary" onClick={onCreate} disabled={busy}>{message ? "Повторить" : "Написать сценарий"}</button>
      </div>
    );
  }
  const first = lines.find((l) => l.name)?.name;
  return (
    <>
      <dl className="dialogue">
        {lines.map((l, i) => (
          <div key={i} style={idx(i)}>
            <dt className={l.name && l.name !== first ? "b" : undefined}>{l.name}</dt>
            <dd>{l.text}</dd>
          </div>
        ))}
      </dl>
      <div className="toolbar">
        <button className="btn small" disabled={busy} onClick={() => confirm("Написать сценарий заново? Аудио тоже придётся создать заново.") && onRegenerate()}>
          Пересоздать сценарий
        </button>
      </div>
    </>
  );
}

export function Audio({ video, job, failure, busy, onCreate }: { video: VideoInfo; job?: Job; failure: Failure | null; busy: boolean; onCreate: () => void }) {
  const id = video.video_id;
  // a new version gets a new URL, so the browser does not keep playing a stale file
  const [version, setVersion] = useState(0);
  const ready = useRef(video.audio_ready);
  useEffect(() => {
    if (video.audio_ready && !ready.current) setVersion(Date.now());
    ready.current = video.audio_ready;
  }, [video.audio_ready]);
  const src = `/api/videos/${id}/audio${version ? `?v=${version}` : ""}`;

  if (video.audio_ready) {
    return (
      <div className="box">
        {/* the API answers Range requests, so playback starts before the whole file is loaded */}
        <audio controls preload="metadata" src={src} />
        <a className="btn small" href={src} download={`${id}.mp3`}>Скачать mp3 ↓</a>
      </div>
    );
  }
  if (job) {
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    return (
      <div className="box">
        <p className="inline accent"><Eq /> {job.status === "queued" ? "Озвучка в очереди…" : `Озвучено ${job.done} из ${job.total || "…"} реплик`}</p>
        <div className="meter" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <i style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }
  return (
    <div className="box">
      {video.podcast_script ? (
        <>
          <p>Аудиоверсия ещё не создана. Сценарий озвучат два голоса ElevenLabs, реплики озвучиваются параллельно.</p>
          <button className="btn primary" onClick={onCreate} disabled={busy}>Создать аудио</button>
        </>
      ) : (
        <p className="muted">Аудио можно будет создать, когда будет готов сценарий подкаста.</p>
      )}
      {failure?.kind === "audio" && <ErrorText error={failure.message} />}
    </div>
  );
}

function hostname(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function Recommendations({ id, initial }: { id: string; initial: Recs | null }) {
  const [recs, setRecs] = useState<Recs | null>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function find() {
    setBusy(true);
    setError(null);
    try {
      setRecs(await api<Recs>(`videos/${id}/recommend`, { method: "POST" }));
    } catch (e) {
      setError(e as Error);
    } finally {
      setBusy(false);
    }
  }

  if (!recs)
    return (
      <div className="box">
        <p>Подберём онлайн-курсы и книги по теме видео на сайтах курсов и книжных магазинов.</p>
        <button className="btn primary" onClick={find} disabled={busy}>
          {busy ? <><Eq /> Ищу…</> : "Найти курсы и книги"}
        </button>
        {error && <ErrorText error={error} />}
      </div>
    );

  return (
    <div className="recs">
      {([["Курсы", recs.courses], ["Книги", recs.books]] as const).map(([title, items]) => (
        <div key={title}>
          <p className="eyebrow">{title}</p>
          {items.length ? (
            <ul>
              {items.map((r, i) => (
                <li key={r.url} style={idx(i)}>
                  <a href={r.url} target="_blank" rel="noreferrer">
                    <span className="rec-title">{r.title || r.url}</span>
                    <span className="arrow">↗</span>
                    <span className="eyebrow">{hostname(r.url)}</span>
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Ничего не найдено.</p>
          )}
        </div>
      ))}
    </div>
  );
}

const SUGGESTIONS = ["О чём это видео?", "Какие главные выводы?", "Объясни ключевые термины простыми словами"];

type Item = { q: string; a: Answer; live: boolean; error?: Error };

export function Questions({ id }: { id: string }) {
  const [items, setItems] = useState<Item[]>([]);
  const [input, setInput] = useState("");
  const pending = items.some((i) => i.live);

  async function ask(q: string) {
    if (!q.trim() || pending) return;
    setInput("");
    // the last answered turns go along, so "а подробнее?" knows what it refers to
    const history = items.filter((i) => !i.live && !i.error && i.a.answer).slice(-3).map((i) => ({ q: i.q, a: i.a.answer }));
    const n = items.length;
    const patch = (p: Partial<Item>) => setItems((prev) => prev.map((it, i) => (i === n ? { ...it, ...p } : it)));
    setItems((prev) => [...prev, { q, a: { answer: "", sources: [] }, live: true }]);
    try {
      await streamAnswer(id, q, history, (a) => patch({ a }));
      patch({ live: false });
    } catch (e) {
      patch({ live: false, error: e as Error });
    }
  }

  return (
    <div className="chat">
      {items.length === 0 && (
        <>
          <p className="muted">Ответы строятся по транскрипту видео, со ссылками на нужные моменты. Можно задавать уточняющие вопросы.</p>
          <div className="suggest">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="btn small" onClick={() => ask(s)}>{s}</button>
            ))}
          </div>
        </>
      )}

      {items.map((it, i) => (
        <div key={i} className="qa fade">
          <div className="q">{it.q}</div>
          {it.error ? <ErrorText error={it.error} /> : <AnswerView a={it.a} id={id} live={it.live} />}
        </div>
      ))}

      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <input className="field" placeholder="Спросите что-нибудь по видео" aria-label="Вопрос" value={input} onChange={(e) => setInput(e.target.value)} />
        <button className="btn primary" disabled={pending || !input.trim()}>Спросить →</button>
      </form>
    </div>
  );
}
