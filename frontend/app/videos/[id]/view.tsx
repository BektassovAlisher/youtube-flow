"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import { api, CATEGORY, linkTimestamps, thumb, type Answer, type Recs, type VideoInfo } from "@/lib/api";
import Eq from "../../eq";

const TABS = ["Конспект", "Проверь себя", "Сценарий", "Аудио", "Рекомендации", "Вопросы"] as const;

const idx = (i: number) => ({ "--i": Math.min(i, 20) }) as CSSProperties;

export default function VideoView({ id, video }: { id: string; video: VideoInfo | null }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Конспект");

  async function remove() {
    if (!confirm("Удалить видео и все материалы по нему?")) return;
    try {
      await api(`videos/${id}`, { method: "DELETE" });
      router.push("/library");
    } catch (e) {
      setError((e as Error).message);
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
          <h3>Видео не найдено</h3>
          <p>Возможно, его удалили. Сгенерируйте его заново на главной.</p>
        </div>
      </>
    );
  const quiz = splitQuiz(video.summary).questions;

  return (
    <>
      {back}

      <div className="vhead">
        <div>
          <p className="eyebrow rise">{[CATEGORY[video.category ?? ""], video.language.toUpperCase()].filter(Boolean).join(" · ")}</p>
          <h1 className="rise" style={{ "--d": 1 } as CSSProperties}>{video.title ?? id}</h1>
          <div className="actions rise" style={{ "--d": 2 } as CSSProperties}>
            <a className="btn small" href={`https://www.youtube.com/watch?v=${id}`} target="_blank" rel="noreferrer">
              Смотреть на YouTube ↗
            </a>
            <button className="btn small danger" onClick={remove}>Удалить</button>
          </div>
          {error && <p className="error">{error}</p>}
        </div>
        <div className="media rise" style={{ "--d": 1 } as CSSProperties}>
          <img className="thumb" src={thumb(id, "hqdefault")} alt="" />
        </div>
      </div>

      <div className="tabs rise" style={{ "--d": 3 } as CSSProperties} role="tablist">
        {TABS.filter((t) => t !== "Проверь себя" || quiz.length > 0).map((t) => (
          <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      <section key={tab} className="panel fade" role="tabpanel">
        {tab === "Конспект" && <Summary video={video} />}
        {tab === "Проверь себя" && <Quiz id={id} questions={quiz} />}
        {tab === "Сценарий" && <Script script={video.podcast_script} />}
        {tab === "Аудио" && <Audio id={id} />}
        {tab === "Рекомендации" && <Recommendations id={id} />}
        {tab === "Вопросы" && <Questions id={id} />}
      </section>
    </>
  );
}

function Markdown({ text, videoId }: { text: string; videoId: string }) {
  return (
    <div className="prose">
      <ReactMarkdown
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer" className={href?.includes("?t=") ? "ts" : undefined}>
              {children}
            </a>
          ),
          h2: ({ node, children }) => <h2 id={`l${node?.position?.start.line}`}>{children}</h2>,
        }}
      >
        {linkTimestamps(text, videoId)}
      </ReactMarkdown>
    </div>
  );
}

// The summary ends with "## Вопросы для самопроверки" + a numbered list: cut it out and render it as quiz cards.
function splitQuiz(md: string) {
  const lines = md.split("\n");
  const start = lines.findIndex((l) => /^##\s*Вопросы для самопроверки/i.test(l));
  if (start < 0) return { body: md, questions: [] };
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

function Summary({ video }: { video: VideoInfo }) {
  if (!video.summary) return <p className="muted">Конспект отсутствует.</p>;
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

function Quiz({ id, questions }: { id: string; questions: string[] }) {
  return (
    <section className="quiz">
      <p className="muted">Сначала ответьте сами, потом откройте ответ — он строится по транскрипту видео.</p>
      <ol className="quiz-list">
        {questions.map((q, i) => (
          <QuizCard key={i} id={id} n={i + 1} q={q} />
        ))}
      </ol>
    </section>
  );
}

function QuizCard({ id, n, q }: { id: string; n: number; q: string }) {
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reveal() {
    setBusy(true);
    setError(null);
    try {
      setAnswer(await api<Answer>(`videos/${id}/qa`, { method: "POST", body: JSON.stringify({ question: q }) }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="quiz-card" data-open={answer ? "" : undefined}>
      <span className="eyebrow">Вопрос {n}</span>
      <p className="quiz-q">{q}</p>
      {answer ? (
        <AnswerView a={answer} id={id} />
      ) : (
        <button className="btn small" onClick={reveal} disabled={busy}>
          {busy ? <><Eq /> Ищу ответ…</> : "Показать ответ"}
        </button>
      )}
      {error && <p className="error">{error}</p>}
    </li>
  );
}

function AnswerView({ a, id }: { a: Answer; id: string }) {
  return (
    <div className="fade">
      <Markdown text={a.answer} videoId={id} />
      {a.sources.length > 0 && (
        <div className="sources">
          <span className="eyebrow">Фрагменты:</span>
          {a.sources.map((s, j) => (
            <a key={j} className="ts" href={s.url} target="_blank" rel="noreferrer">{s.timestamp}</a>
          ))}
        </div>
      )}
    </div>
  );
}

function Script({ script }: { script: string }) {
  const lines = script
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const i = l.indexOf(":");
      const name = i > 0 ? l.slice(0, i).replace(/\*/g, "").trim() : "";
      return name && name.length <= 20 ? { name, text: l.slice(i + 1).replace(/^[\s*]+/, "") } : { name: "", text: l };
    });
  const first = lines.find((l) => l.name)?.name;
  if (!lines.length) return <p className="muted">Сценарий отсутствует.</p>;
  return (
    <dl className="dialogue">
      {lines.map((l, i) => (
        <div key={i} style={idx(i)}>
          <dt className={l.name && l.name !== first ? "b" : undefined}>{l.name}</dt>
          <dd>{l.text}</dd>
        </div>
      ))}
    </dl>
  );
}

function Audio({ id }: { id: string }) {
  const [state, setState] = useState<"checking" | "none" | "generating" | "ready">("checking");
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // fetched as a blob: the API doesn't serve Range requests, which Safari needs for <audio src>
  async function load() {
    const res = await fetch(`/api/videos/${id}/audio`);
    if (!res.ok) return false;
    setSrc(URL.createObjectURL(await res.blob()));
    setState("ready");
    return true;
  }

  useEffect(() => {
    load().then((ok) => !ok && setState("none"));
  }, [id]);
  useEffect(() => () => void (src && URL.revokeObjectURL(src)), [src]);

  async function generate() {
    setState("generating");
    setError(null);
    try {
      await api(`videos/${id}/audio`, { method: "POST" });
      await load();
    } catch (e) {
      setError((e as Error).message);
      setState("none");
    }
  }

  return (
    <div className="box">
      {state === "checking" && <p className="inline muted"><Eq /> Проверяю аудио…</p>}
      {state === "ready" && src && (
        <>
          <audio controls src={src} />
          <a className="btn small" href={src} download={`${id}.mp3`}>Скачать mp3 ↓</a>
        </>
      )}
      {state === "none" && (
        <>
          <p>Аудиоверсия ещё не создана. Сценарий озвучат два голоса ElevenLabs — это занимает 1–3 минуты.</p>
          <button className="btn primary" onClick={generate}>Создать аудио</button>
        </>
      )}
      {state === "generating" && (
        <p className="inline accent"><Eq /> Идёт озвучка…</p>
      )}
      {error && <p className="error">{error}</p>}
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

function Recommendations({ id }: { id: string }) {
  const [recs, setRecs] = useState<Recs | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function find() {
    setBusy(true);
    setError(null);
    try {
      setRecs(await api<Recs>(`videos/${id}/recommend`, { method: "POST" }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!recs)
    return (
      <div className="box">
        <p>Подберём онлайн-курсы и книги по теме видео через веб-поиск.</p>
        <button className="btn primary" onClick={find} disabled={busy}>
          {busy ? <><Eq /> Ищу…</> : "Найти курсы и книги"}
        </button>
        {error && <p className="error">{error}</p>}
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

function Questions({ id }: { id: string }) {
  const [items, setItems] = useState<{ q: string; a?: Answer; error?: string }[]>([]);
  const [input, setInput] = useState("");
  const pending = items.some((i) => !i.a && !i.error);

  async function ask(q: string) {
    if (!q.trim() || pending) return;
    setInput("");
    setItems((prev) => [...prev, { q }]);
    const done = (patch: { a?: Answer; error?: string }) =>
      setItems((prev) => prev.map((it, i) => (i === prev.length - 1 ? { ...it, ...patch } : it)));
    try {
      done({ a: await api<Answer>(`videos/${id}/qa`, { method: "POST", body: JSON.stringify({ question: q }) }) });
    } catch (e) {
      done({ error: (e as Error).message });
    }
  }

  return (
    <div className="chat">
      {items.length === 0 && (
        <>
          <p className="muted">Ответы строятся по транскрипту видео, со ссылками на нужные моменты.</p>
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
          {it.a && <AnswerView a={it.a} id={id} />}
          {it.error && <p className="error">{it.error}</p>}
          {!it.a && !it.error && <p className="inline accent"><Eq /> Ищу ответ в транскрипте…</p>}
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
