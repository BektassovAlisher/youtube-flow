"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type CSSProperties } from "react";
import { api, CATEGORY, type GenerateResult } from "@/lib/api";
import Eq from "./eq";

const CHIPS = ["Конспект с таймкодами", "Диалог двух ведущих", "Ответы по видео", "RU · EN · KK"];

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

const d = (n: number) => ({ "--d": n }) as CSSProperties;

// typewriter for the wordmark: uneven gaps between keystrokes (ms) read as a person typing;
// fixed values so the server-rendered HTML and the client agree
const WORD = "VideoFlow";
const GAPS = [0, 120, 85, 140, 95, 170, 80, 125, 100];
const KEYSTROKES = GAPS.map((_, i) => 400 + GAPS.slice(0, i + 1).reduce((a, b) => a + b, 0));
const DONE = KEYSTROKES[KEYSTROKES.length - 1] + 500;

export default function GeneratePage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [rejected, setRejected] = useState<GenerateResult | null>(null);
  const [ripple, setRipple] = useState<{ x: number; y: number; key: number } | null>(null);

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
    setError(null);
    setRejected(null);
    try {
      const res = await api<GenerateResult>("generate", {
        method: "POST",
        body: JSON.stringify({ video_url: url.trim(), skip_audio: true }),
      });
      if (res.rejected) setRejected(res);
      else router.push(`/videos/${res.video_id}`);
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
        <p className="eyebrow rise">YouTube → конспект → подкаст</p>
        <h1 className="hero-title" aria-label={WORD}>
          {[...WORD].map((c, i) => (
            <span key={i} className="ch" style={{ "--t": `${KEYSTROKES[i]}ms` } as CSSProperties} aria-hidden>
              {c}
            </span>
          ))}
          <span className="caret" style={{ "--done": `${DONE}ms` } as CSSProperties} aria-hidden />
        </h1>
        <p className="subtitle rise" style={d(5)}>
          Конспекты, сценарии и подкасты из обучающих видео на YouTube.
        </p>
        <div className="chips rise" style={d(6)}>
          {CHIPS.map((c) => (
            <span key={c} className="chip">{c}</span>
          ))}
        </div>

        <form className="form rise" style={d(7)} onSubmit={submit}>
          <input
            className="field"
            type="url"
            required
            placeholder="https://www.youtube.com/watch?v=…"
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
          <>
            <div className="progress" />
            <p className="hint muted">Обычно это занимает от 30 секунд до пары минут — зависит от длины видео.</p>
          </>
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
