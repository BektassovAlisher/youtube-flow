"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { api, ApiError, CATEGORY, cover, kindLabel, lengthLabel, notEducational, siteOf, uploadDocument, type VideoInfo, type VideoListItem } from "@/lib/api";
import CoverImage from "./cover-image";
import Eq from "./eq";
import ErrorText from "./error-text";

// What the server does after the button, in the order the progress list on the material page shows it
const STEPS: [string, string][] = [
  ["Текст.", "Субтитры видео или распознанная речь, основной текст статьи без меню и рекламы, ваш текст или файл."],
  ["Проверка.", "Модель смотрит, учебный ли это материал. Клипы и рекламу она отклонит, но их можно обработать вручную. Вставленный текст не проверяется."],
  ["Конспект.", "Разделы с таймкодами или номерами абзацев, определения, выводы и вопросы для самопроверки. Текст появляется по мере написания."],
  ["Термины.", "10–15 главных понятий из оглавления конспекта."],
  ["Сценарий подкаста.", "Диалог двух ведущих. Редактор проверяет его и может вернуть на доработку."],
  ["По кнопке.", "Озвучка на два голоса, ответы на вопросы со ссылками на нужные места, подборка курсов и книг."],
];

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

  // the server answers at once (the work runs in the background); progress is shown on the material page
  async function start(force = false, file?: File) {
    setBusy(true);
    setError(null);
    setRejected(null);
    try {
      const body = mode === "text" ? { text, title: title.trim() || undefined } : { url: url.trim(), force };
      const video = file
        ? await uploadDocument(file, title.trim() || undefined)
        : await api<VideoInfo>("videos", { method: "POST", body: JSON.stringify(body) });
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
  const submit = (
    <button className="btn primary" disabled={busy || !ready}>
      {busy ? (
        <>
          <Eq /> Отправляю…
        </>
      ) : (
        "Сделать конспект"
      )}
    </button>
  );

  return (
    <div className="home">
      <div>
        <section className="intro">
          <h1>
            <mark className="hl">Конспект</mark> лекции, статьи или PDF
          </h1>
          <p className="lede">
            Вставьте ссылку на видео, подкаст или статью либо сам текст. Получится конспект с таймкодами, вопросы для
            самопроверки, подкаст на два голоса и ответы на вопросы по материалу.
          </p>
        </section>

        <div className="composer">
          <div className="mode" role="tablist" aria-label="Что добавить">
            {(["link", "text"] as const).map((m) => (
              <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)} disabled={busy}>
                {m === "link" ? "Ссылка" : "Текст или файл"}
              </button>
            ))}
          </div>

          <form
            className="form-block"
            onSubmit={(e) => {
              e.preventDefault();
              start();
            }}
          >
            {mode === "link" ? (
              <>
                <label className="field-label" htmlFor="material-url">Ссылка на видео, подкаст или статью</label>
                <div className="form">
                  <input
                    id="material-url"
                    className="field"
                    type="text"
                    inputMode="url"
                    autoComplete="off"
                    spellCheck={false}
                    required
                    placeholder="https://"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    disabled={busy}
                  />
                  {submit}
                </div>
              </>
            ) : (
              <div className="text-fields">
                <label className="field-label" htmlFor="material-title">Название, если нужно своё</label>
                <input
                  id="material-title"
                  className="field"
                  maxLength={300}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={busy}
                />
                <label className="field-label" htmlFor="material-text">Текст статьи, главы, лекции или своих заметок</label>
                <textarea
                  id="material-text"
                  className="field textarea"
                  required
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  disabled={busy}
                />
                <div className="text-foot">
                  <span className="muted num">
                    {text.length < MIN_TEXT
                      ? `Нужно хотя бы ${MIN_TEXT} символов, сейчас ${text.length}`
                      : `${text.length.toLocaleString("ru-RU")} символов`}
                  </span>
                  <label className="btn small upload" aria-disabled={busy || undefined}>
                    Загрузить файл: PDF, TXT или MD
                    <input
                      type="file"
                      accept=".pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown"
                      disabled={busy}
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        e.target.value = ""; // the same file can be picked again after an error
                        if (file) start(false, file);
                      }}
                    />
                  </label>
                </div>
                {submit}
              </div>
            )}
          </form>

          {error && <ErrorText error={error} />}

          {rejected && (
            <div className="notice" role="status">
              <h3>{notEducational(rejected.kind)}</h3>
              <p>Категория: {CATEGORY[rejected.classification?.category ?? "unknown"] ?? rejected.classification?.category}</p>
              {rejected.classification?.reason && <p>{rejected.classification.reason}</p>}
              <p className="muted">Конспект лучше всего получается из лекций, уроков, руководств и разборов.</p>
              <div className="actions">
                <button className="btn small" onClick={() => start(true)} disabled={busy}>
                  Всё равно обработать
                </button>
              </div>
            </div>
          )}
        </div>

        {examples.length > 0 && (
          <section className="recent" aria-labelledby="recent">
            <div className="recent-head">
              <h2 className="label" id="recent">Недавние</h2>
              <Link href="/library">Вся библиотека</Link>
            </div>
            <ul className="rows compact">
              {examples.map((v) => (
                <li key={v.video_id}>
                  <Link href={`/videos/${v.video_id}`} className="row">
                    <CoverImage src={cover(v)} label={kindLabel(v)} />
                    <span>
                      <span className="row-title">{v.title ?? v.video_id}</span>
                      <span className="row-meta">
                        {[kindLabel(v), v.kind !== "youtube" && (v.channel || (v.url && siteOf(v.url))), v.language?.toUpperCase(), lengthLabel(v)]
                          .filter((x, i, all) => x && all.indexOf(x) === i)
                          .join(" · ")}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <aside className="margin" aria-labelledby="steps">
        <h2 className="label" id="steps">Что будет после нажатия</h2>
        <ol className="steps">
          {STEPS.map(([name, text]) => (
            <li key={name}>
              <span>
                <b>{name}</b> {text}
              </span>
            </li>
          ))}
        </ol>
        <p>Страницу можно закрыть: обработка идёт на сервере, а готовый материал появится в библиотеке.</p>
      </aside>
    </div>
  );
}
