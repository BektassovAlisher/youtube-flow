"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import { api, CATEGORY, linkTimestamps, thumb, type Answer, type Recs, type VideoInfo } from "@/lib/api";
import Eq from "../../eq";

const TABS = ["Конспект", "Сценарий", "Аудио", "Рекомендации", "Вопросы"] as const;

const idx = (i: number) => ({ "--i": Math.min(i, 20) }) as CSSProperties;

export default function VideoPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [video, setVideo] = useState<VideoInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Конспект");

  useEffect(() => {
    api<VideoInfo>(`videos/${id}`)
      .then(setVideo)
      .catch((e) => setError(e.message));
  }, [id]);

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

  if (error && !video)
    return (
      <>
        {back}
        <div className="notice fade">
          <h3>Видео не найдено</h3>
          <p>Возможно, его удалили. Сгенерируйте его заново на главной.</p>
        </div>
      </>
    );
  if (!video)
    return (
      <p className="inline muted">
        <Eq /> Загрузка…
      </p>
    );

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
        {TABS.map((t) => (
          <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      <section key={tab} className="panel fade" role="tabpanel">
        {tab === "Конспект" && <Summary video={video} />}
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
        }}
      >
        {linkTimestamps(text, videoId)}
      </ReactMarkdown>
    </div>
  );
}

function Summary({ video }: { video: VideoInfo }) {
  return (
    <>
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
      {video.summary ? <Markdown text={video.summary} videoId={video.video_id} /> : <p className="muted">Конспект отсутствует.</p>}
    </>
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
          {it.a && (
            <div className="fade">
              <Markdown text={it.a.answer} videoId={id} />
              {it.a.sources.length > 0 && (
                <div className="sources">
                  <span className="eyebrow">Фрагменты:</span>
                  {it.a.sources.map((s, j) => (
                    <a key={j} className="ts" href={s.url} target="_blank" rel="noreferrer">{s.timestamp}</a>
                  ))}
                </div>
              )}
            </div>
          )}
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
