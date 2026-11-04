"use client";

import { useRouter } from "next/navigation";
import { useState, type CSSProperties } from "react";
import Link from "next/link";
import { api, ApiError, CATEGORY, cover, KIND_LABEL, lengthLabel, notEducational, siteOf, type VideoInfo, type VideoListItem } from "@/lib/api";
import CoverImage from "./cover-image";
import Eq from "./eq";
import ErrorText from "./error-text";

const TRANSCRIPT = [
  ["00:04", "Представьте, что вы видите цифру три"],
  ["00:11", "Мозг узнаёт её мгновенно"],
  ["00:19", "Нейросеть — это просто функция"],
  ["00:26", "У каждого нейрона есть вес"],
  ["00:34", "Обучение — это поиск минимума"],
];
const WAVE = [40, 70, 55, 90, 65, 100, 45, 80, 60, 95, 50, 75, 35, 85, 60, 45, 70, 30, 55, 80, 40, 65, 50, 35];

// each card previews what that step actually produces
const STEPS = [
  {
    title: "Текст",
    text: "Берём субтитры видео, основной текст статьи без меню и рекламы или ваш текст.",
    preview: (
      <div className="pv-roll">
        {[...TRANSCRIPT, ...TRANSCRIPT].map(([t, line], i) => (
          <div key={i}>
            <span className="t">{t}</span>
            {line}
          </div>
        ))}
      </div>
    ),
  },
  {
    title: "Проверка",
    text: "Пропускаем учебные материалы — клипы, рекламу и пустые страницы отсеиваем.",
    preview: (
      <>
        <div className="pv-row"><span className="ok">✓</span> Лекция по ML <em>0.98</em></div>
        <div className="pv-row dim"><span className="no">✕</span> Музыкальный клип <em>0.99</em></div>
        <div className="pv-row"><span className="ok">✓</span> Курс по Python <em>0.95</em></div>
      </>
    ),
  },
  {
    title: "Конспект",
    text: "Разделы с таймкодами, ключевые термины и вопросы для самопроверки.",
    preview: (
      <>
        <div className="pv-h"><span className="t">04:12</span>Градиентный спуск</div>
        <div className="pv-line" style={{ width: "92%" }} />
        <div className="pv-line" style={{ width: "78%" }} />
        <div className="chips"><span className="chip">функция стоимости</span><span className="chip">шаг обучения</span></div>
      </>
    ),
  },
  {
    title: "Сценарий подкаста",
    text: "Диалог двух ведущих: Алекс спрашивает, Марина объясняет. Редактор проверяет каждую версию.",
    preview: (
      <>
        <div className="pv-msg"><b>Алекс</b>А что вообще такое градиент?</div>
        <div className="pv-msg b"><b>Марина</b>Представь, что спускаешься с горы в тумане и идёшь туда, где круче всего вниз.</div>
      </>
    ),
  },
  {
    title: "Аудио и вопросы",
    text: "Озвучка двумя голосами и ответы на вопросы со ссылками на моменты видео.",
    preview: (
      <>
        <div className="pv-player">
          <span className="pv-play">▶</span>
          <span className="pv-wave">
            {WAVE.map((h, i) => (
              <i key={i} style={{ "--h": `${h}%`, "--i": i } as CSSProperties} />
            ))}
          </span>
          <span className="muted">2:35</span>
        </div>
        <div className="pv-ask">Что такое веса? <span className="t">→ 12:05</span></div>
      </>
    ),
  },
];

const d = (n: number) => ({ "--d": n }) as CSSProperties;

// typewriter for the headline: uneven gaps between keystrokes (ms) read as a person typing;
// fixed values so the server-rendered HTML and the client agree
const WORD = "Конспект любого видео или статьи";
const GAPS = Array.from(WORD, (_, i) => (i ? 40 + ((i * 29) % 50) : 0));
const KEYSTROKES = GAPS.map((_, i) => 150 + GAPS.slice(0, i + 1).reduce((a, b) => a + b, 0));
const DONE = KEYSTROKES[KEYSTROKES.length - 1] + 500;

const MIN_TEXT = 300;

export default function Home({ examples }: { examples: VideoListItem[] }) {
  const router = useRouter();
  const [mode, setMode] = useState<"link" | "text">("link");
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [rejected, setRejected] = useState<VideoInfo | null>(null);
  const [ripple, setRipple] = useState<{ x: number; y: number; key: number } | null>(null);

  // the server answers at once (the work runs in the background); progress is shown on the video page
  async function start(force = false) {
    setBusy(true);
    setError(null);
    setRejected(null);
    try {
      const body = mode === "text" ? { text, title: title.trim() || undefined } : { url: url.trim(), force };
      const video = await api<VideoInfo>("videos", { method: "POST", body: JSON.stringify(body) });
      if (video.status === "rejected") {
        setRejected(video);
        setBusy(false);
      } else {
        router.push(`/videos/${video.video_id}`);
      }
    } catch (err) {
      setError(err as ApiError);
      setBusy(false);
    }
  }

  const ready = mode === "link" ? url.trim().length > 0 : text.trim().length >= MIN_TEXT;

  return (
    <>
      <section className="hero">
        <h1 className="hero-title" aria-label={WORD}>
          {/* invisible full copy reserves the final height, so nothing below jumps when typing wraps a line */}
          <span className="ghost" aria-hidden>
            {WORD}
            <span className="caret" />
          </span>
          <span aria-hidden>
            {[...WORD].map((c, i) => (
              <span key={i} className="ch" style={{ "--t": `${KEYSTROKES[i]}ms` } as CSSProperties}>
                {c}
              </span>
            ))}
            <span className="caret" style={{ "--done": `${DONE}ms` } as CSSProperties} />
          </span>
        </h1>
        <p className="subtitle rise" style={d(1)}>
          Вставьте ссылку на обучающее видео или статью — или сам текст. Получите конспект, вопросы для самопроверки,
          подкаст на два голоса и ответы по материалу.
        </p>

        <div className="mode rise" style={d(2)} role="tablist" aria-label="Что добавить">
          {(["link", "text"] as const).map((m) => (
            <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)} disabled={busy}>
              {m === "link" ? "Ссылка" : "Текст"}
            </button>
          ))}
        </div>

        <form
          className={`form rise${mode === "text" ? " text-form" : ""}`}
          style={d(2)}
          onSubmit={(e) => {
            e.preventDefault();
            start();
          }}
        >
          {mode === "link" ? (
            <input
              className="field"
              type="text"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              required
              placeholder="Ссылка на видео YouTube или на статью"
              aria-label="Ссылка на видео или статью"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={busy}
            />
          ) : (
            <div className="text-fields">
              <input
                className="field"
                placeholder="Название (необязательно)"
                aria-label="Название"
                maxLength={300}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={busy}
              />
              <textarea
                className="field textarea"
                required
                placeholder="Вставьте текст статьи, главы, лекции или своих заметок"
                aria-label="Текст"
                value={text}
                onChange={(e) => setText(e.target.value)}
                disabled={busy}
              />
              <span className="muted text-count">
                {text.length < MIN_TEXT ? `Нужно хотя бы ${MIN_TEXT} символов — сейчас ${text.length}` : `${text.length.toLocaleString("ru-RU")} символов`}
              </span>
            </div>
          )}
          <span className="cta" data-waiting={busy || !ready || undefined}>
            <span className="cta-glow" aria-hidden>
              <i />
            </span>
            <span className="cta-ring" aria-hidden>
              <i />
            </span>
            <button
              className="btn primary"
              disabled={busy || !ready}
              onPointerDown={(e) => {
                const r = e.currentTarget.getBoundingClientRect();
                setRipple({ x: e.clientX - r.left, y: e.clientY - r.top, key: e.timeStamp });
              }}
            >
              {ripple && <span key={ripple.key} className="ripple" style={{ "--x": `${ripple.x}px`, "--y": `${ripple.y}px` } as CSSProperties} />}
              {busy ? (
                <>
                  <Eq /> Отправляю…
                </>
              ) : (
                "Создать →"
              )}
            </button>
          </span>
        </form>

        {error && <ErrorText error={error} />}

        {rejected && (
          <div className="notice fade" role="status">
            <h3>{notEducational(rejected.kind)}</h3>
            <p>Категория: {CATEGORY[rejected.classification?.category ?? "unknown"] ?? rejected.classification?.category}</p>
            {rejected.classification?.reason && <p>{rejected.classification.reason}</p>}
            <p className="muted">Конспект лучше всего получается из лекций, уроков, руководств и разборов.</p>
            <div className="actions notice-actions">
              <button className="btn small" onClick={() => start(true)} disabled={busy}>
                Всё равно обработать
              </button>
            </div>
          </div>
        )}

        {examples.length > 0 && !busy && (
          <div className="examples rise" style={d(3)}>
            <p className="eyebrow">Или откройте готовый пример</p>
            <ul className="examples-list">
              {examples.map((v) => (
                <li key={v.video_id}>
                  <Link href={`/videos/${v.video_id}`} className="example">
                    <CoverImage src={cover(v)} label={KIND_LABEL[v.kind]} />
                    <span>
                      <b>{v.title ?? v.video_id}</b>
                      <small>
                        {[v.kind !== "youtube" && (v.channel || (v.url && siteOf(v.url)) || KIND_LABEL[v.kind]), v.language?.toUpperCase(), lengthLabel(v)]
                          .filter(Boolean)
                          .join(" · ")}
                      </small>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="section">
        <h2 className="section-title reveal">Как это работает</h2>
        <ol className="steps reveal">
          {STEPS.map((s, i) => (
            <li key={s.title} className="step">
              <div className="pv" aria-hidden>{s.preview}</div>
              <div className="step-body">
                <span className="step-n">{String(i + 1).padStart(2, "0")}</span>
                <b>{s.title}</b>
                <p>{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}
