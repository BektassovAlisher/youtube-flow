export type VideoStatus = "processing" | "ready" | "rejected" | "failed";
export type Kind = "youtube" | "article" | "text";

export type VideoListItem = {
  video_id: string;
  kind: Kind;
  title: string | null;
  url: string;
  language: string | null;
  duration_sec: number | null;
  category: string | null;
  channel: string | null; // the site for articles
  image_url: string | null; // article cover
  word_count: number | null; // articles and pasted text
  status: VideoStatus;
  created_at: string | null;
};

// what links to places inside a material need
export type Material = Pick<VideoListItem, "video_id" | "kind" | "url"> & { anchors?: Record<string, string> | null };

export type Job = { kind: "process" | "audio"; status: "queued" | "running"; stage: string | null; done: number; total: number };
export type Classification = { category: string; is_suitable: boolean; confidence: number; reason: string };
export type Link = { title: string; url: string };
export type Recs = { courses: Link[]; books: Link[]; from_cache?: boolean };
export type Source = { timestamp: string; url: string };
export type Answer = { answer: string; sources: Source[] };

export type VideoInfo = VideoListItem & {
  summary: string;
  keywords: string[];
  podcast_script: string;
  recommendation: Recs | null;
  audio_ready: boolean;
  stage: string | null;
  error: string | null;
  classification: Classification | null;
  force: boolean;
  indexed: boolean;
  transcript_source: string | null;
  anchors: Record<string, string> | null;
  jobs: Job[];
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

// Browser talks to /api/*, which app/api/[...path]/route.ts forwards to FastAPI.
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/${path}`, { ...init, headers: { "content-type": "application/json" } });
  if (!res.ok) await fail(res);
  return res.json();
}

export async function fail(res: Response): Promise<never> {
  const body = await res.json().catch(() => null);
  const message = typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`;
  throw new ApiError(message, res.status);
}

// NDJSON stream: one JSON object per line
export async function readNdjson(res: Response, onEvent: (event: any) => void) {
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  const emit = (line: string) => {
    if (!line.trim()) return;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      return; // a broken line (proxy hiccup) is skipped, the next ones still arrive
    }
    onEvent(event); // errors thrown by the handler propagate to the caller
  };
  for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
    const lines = (buf + chunk.value).split("\n");
    buf = lines.pop()!;
    lines.forEach(emit);
  }
  emit(buf);
}

export type AnswerEvent =
  | { type: "sources"; sources: Source[] }
  | { type: "token"; text: string }
  | { type: "done"; cached: boolean }
  | { type: "error"; message: string };

export async function askStream(id: string, question: string, history: { q: string; a: string }[], onEvent: (e: AnswerEvent) => void) {
  const res = await fetch(`/api/videos/${id}/qa/stream`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
  if (!res.ok || !res.body) await fail(res);
  await readNdjson(res, onEvent);
}

// pipeline stages as the API reports them (job.stage); pasted text skips the check
export function stagesFor(kind: Kind): [string, string][] {
  return [
    ["transcript", kind === "article" ? "Загружаю статью" : kind === "text" ? "Разбираю текст" : "Получаю субтитры"],
    ...(kind === "text" ? [] : ([["classify", kind === "article" ? "Проверяю, что это учебный материал" : "Проверяю, что это обучающее видео"]] as [string, string][])),
    ["summary", "Пишу конспект"],
    ["keywords", "Выделяю ключевые термины"],
    ["script", "Пишу сценарий подкаста — редактор проверяет"],
  ];
}

export const KIND_LABEL: Record<Kind, string> = { youtube: "Видео", article: "Статья", text: "Текст" };
export const notEducational = (kind: Kind) => (kind === "article" ? "Похоже, это не учебный материал" : "Похоже, это не обучающее видео");

export const CATEGORY: Record<string, string> = {
  educational: "Образование",
  entertainment: "Развлечения",
  news: "Новости",
  music: "Музыка",
  gaming: "Игры",
  random: "Разное",
  advertising: "Реклама",
  unknown: "Без категории",
};

export function addedOn(createdAt: string | null): string | null {
  if (!createdAt) return null;
  const utc = /Z|[+-]\d\d:\d\d$/.test(createdAt) ? createdAt : createdAt + "Z"; // API sends naive UTC
  return new Date(utc).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export const thumb = (id: string, size = "mqdefault") => `https://img.youtube.com/vi/${id}/${size}.jpg`;

// picture for cards: the video frame, the article's cover, or none (a placeholder is drawn)
export const cover = (v: Pick<VideoListItem, "video_id" | "kind" | "image_url">, size?: string) =>
  v.kind === "youtube" ? thumb(v.video_id, size) : v.image_url;

export const minutes = (sec: number | null) => (sec ? `${Math.round(sec / 60)} мин` : null);
export const readingTime = (words: number | null) => (words ? `${Math.max(1, Math.round(words / 180))} мин чтения` : null);
export const lengthLabel = (v: Pick<VideoListItem, "kind" | "duration_sec" | "word_count">) =>
  v.kind === "youtube" ? minutes(v.duration_sec) : readingTime(v.word_count);

export const siteOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
};

// "[12:34]" / "[1:02:03]" -> markdown link to that moment of the video
export function linkTimestamps(md: string, videoId: string): string {
  return md.replace(/\[(\d{1,2}):(\d{2})(?::(\d{2}))?\](?!\()/g, (m, a, b, c) => {
    const sec = c ? +a * 3600 + +b * 60 + +c : +a * 60 + +b;
    return `[${m.slice(1, -1)}](https://youtu.be/${videoId}?t=${sec})`;
  });
}

// "[¶12]" -> the 12th paragraph: in the original page (text fragment) for articles, on this page for pasted text
export function fragmentUrl(url: string, words?: string | null) {
  return words ? `${url}#:~:text=${encodeURIComponent(words).replace(/-/g, "%2D")}` : url;
}

export function linkLocators(md: string, m: Material): string {
  if (m.kind === "youtube") return linkTimestamps(md, m.video_id);
  return md.replace(/\[¶(\d+)\](?!\()/g, (_, n) => `[¶${n}](${m.kind === "text" ? `#p${n}` : fragmentUrl(m.url, m.anchors?.[n])})`);
}

export const paragraphTarget = (href: string | undefined) => {
  const m = href?.match(/^#p(\d+)$/);
  return m ? +m[1] : null;
};

// seconds of a youtu.be/<id>?t=<sec> link to this very video, else null
export function seekTarget(href: string | undefined, videoId: string): number | null {
  const m = href?.match(/^https:\/\/youtu\.be\/([\w-]{11})\?t=(\d+)$/);
  return m && m[1] === videoId ? +m[2] : null;
}
