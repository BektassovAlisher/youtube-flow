"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type CSSProperties } from "react";
import Link from "next/link";
import { CATEGORY, fail, minutes, thumb, type GenerateResult, type VideoListItem } from "@/lib/api";
import Eq from "./eq";

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
    title: "Транскрипт",
    text: "Берём субтитры видео на русском, английском или казахском.",
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
    text: "Пропускаем только обучающие видео — клипы и влоги отсеиваются.",
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

// stages shown while a new video is processed; each is done when its graph node finishes (/generate/stream)
const STAGES = [
  ["extract_transcript", "Получаю субтитры"],
  ["classify", "Проверяю, что это обучающее видео"],
  ["merge", "Пишу конспект и выделяю термины"],
  ["save_to_db", "Пишу сценарий подкаста — редактор проверяет"],
] as const;

const d = (n: number) => ({ "--d": n }) as CSSProperties;

// typewriter for the headline: uneven gaps between keystrokes (ms) read as a person typing;
// fixed values so the server-rendered HTML and the client agree
const WORD = "Конспект любого урока с YouTube";
const GAPS = Array.from(WORD, (_, i) => (i ? 40 + ((i * 29) % 50) : 0));
const KEYSTROKES = GAPS.map((_, i) => 150 + GAPS.slice(0, i + 1).reduce((a, b) => a + b, 0));
const DONE = KEYSTROKES[KEYSTROKES.length - 1] + 500;

export default function Home({ examples }: { examples: VideoListItem[] }) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [rejected, setRejected] = useState<GenerateResult | null>(null);
  const [ripple, setRipple] = useState<{ x: number; y: number; key: number } | null>(null);
  const [stage, setStage] = useState(0); // how many STAGES are done


  useEffect(() => {
    if (!busy) return;
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [busy]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setElapsed(0);
    setStage(0);
    setError(null);
    setRejected(null);
    try {
      const res = await fetch("/api/generate/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ video_url: url.trim(), skip_audio: true }),
      });
      if (!res.ok || !res.body) await fail(res);
      let result: GenerateResult | null = null;
      let buf = "";
      const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
      for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
        const lines = (buf + chunk.value).split("\n");
        buf = lines.pop()!;
        for (const line of lines.filter(Boolean)) {
          const ev = JSON.parse(line);
          if (ev.error) throw new Error(ev.error);
          if (ev.result) result = ev.result;
          const i = STAGES.findIndex(([node]) => node === ev.step);
          if (i >= 0) setStage((s) => Math.max(s, i + 1));
        }
      }
      if (!result) throw new Error("Обработка прервалась, попробуйте ещё раз");
      if (result.rejected) setRejected(result);
      else router.push(`/videos/${result.video_id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const clock = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;

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
          Вставьте ссылку на обучающее видео — получите конспект с таймкодами, подкаст на два голоса и ответы на вопросы по
          видео. Русский, английский, казахский.
        </p>

        <form className="form rise" style={d(2)} onSubmit={submit}>
          <input
            className="field"
            type="url"
            required
            placeholder="Ссылка на видео с YouTube"
            aria-label="Ссылка на YouTube"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={busy}
          />
          <span className="cta" data-waiting={busy || !url.trim() || undefined}>
            <button
              className="btn primary"
              disabled={busy || !url.trim()}
              onPointerDown={(e) => {
                const r = e.currentTarget.getBoundingClientRect();
                setRipple({ x: e.clientX - r.left, y: e.clientY - r.top, key: e.timeStamp });
              }}
            >
              {ripple && <span key={ripple.key} className="ripple" style={{ "--x": `${ripple.x}px`, "--y": `${ripple.y}px` } as CSSProperties} />}
              {busy ? (
                <>
                  <Eq /> Обработка {clock}
                </>
              ) : (
                "Создать →"
              )}
            </button>
          </span>
        </form>

        {busy && (
          <ol className="stages fade" aria-live="polite">
            {STAGES.map(([node, label], i) => (
              <li key={node} data-state={i < stage ? "done" : i === stage ? "active" : undefined}>
                <span className="stage-mark">{i < stage ? "✓" : i === stage ? <Eq /> : ""}</span>
                {label}
              </li>
            ))}
            <li className="stages-hint">Обычно это занимает от 30 секунд до пары минут — зависит от длины видео.</li>
          </ol>
        )}
        {error && <p className="error fade">{error}</p>}

        {rejected && (
          <div className="notice fade" role="status">
            <h3>Видео не подходит для обработки</h3>
            <p>Категория: {CATEGORY[rejected.video_category ?? "unknown"] ?? rejected.video_category}</p>
            {rejected.classification_reason && <p>{rejected.classification_reason}</p>}
            <p className="muted">Выберите обучающее видео: лекцию, туториал или курс.</p>
          </div>
        )}

        {examples.length > 0 && !busy && (
          <div className="examples rise" style={d(3)}>
            <p className="eyebrow">Или откройте готовый пример</p>
            <ul className="examples-list">
              {examples.map((v) => (
                <li key={v.video_id}>
                  <Link href={`/videos/${v.video_id}`} className="example">
                    <img className="thumb" src={thumb(v.video_id)} alt="" loading="lazy" />
                    <span>
                      <b>{v.title ?? v.video_id}</b>
                      <small>{[v.language?.toUpperCase(), minutes(v.duration_sec)].filter(Boolean).join(" · ")}</small>
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
