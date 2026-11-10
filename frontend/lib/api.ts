export type VideoStatus = "processing" | "ready" | "rejected" | "failed";
export type Kind = "youtube" | "media" | "article" | "text";

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
  source?: string | null; // where the text came from: manual | generated | whisper | article | pasted | pdf | file
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
export type Answer = { answer: string; sources: Source[]; seconds?: number };

// how the processing went, saved by the API: seconds per step, time to the first words, tokens, model
export type Metrics = {
  seconds: number;
  steps: Record<string, number>;
  tokens?: { input?: number; output?: number };
  first_token?: number;
  audio?: number;
  model?: string;
  runs?: number;
};

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
  metrics: Metrics | null;
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
  | { type: "done"; cached: boolean; seconds?: number }
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

// pipeline stages as the API reports them (job.stage); the check runs alongside the summary, so it has no line here
export function stagesFor(kind: Kind): [string, string][] {
  return [
    ["transcript", { youtube: "Получаю субтитры", media: "Получаю субтитры или распознаю речь", article: "Загружаю статью", text: "Разбираю текст" }[kind]],
    ["summary", "Пишу конспект"],
    ["keywords", "Выделяю ключевые термины"],
    ["script", "Пишу сценарий подкаста, редактор его проверяет"],
  ];
}

// Russian plural: 1 материал, 2 материала, 5 материалов, 21 материал
export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

export const KIND_LABEL: Record<Kind, string> = { youtube: "Видео", media: "Запись", article: "Статья", text: "Текст" };
export const notEducational = (kind: Kind) =>
  kind === "article" ? "Похоже, это не учебный материал" : kind === "media" ? "Похоже, это не обучающая запись" : "Похоже, это не обучающее видео";

// recordings from other sites (mirrors backend/app/tools/media.py)
const AUDIO_SITES = ["soundcloud.com", "podcasts.apple.com", "mixcloud.com"];
const AUDIO_FILE = /\.(mp3|m4a|aac|ogg|oga|opus|wav|flac)$/i;
const VIDEO_FILE = /\.(mp4|m4v|mov|webm|mkv)$/i;
const pathOf = (url: string) => {
  try {
    return new URL(url).pathname;
  } catch {
    return "";
  }
};
export const isAudioFile = (url: string) => AUDIO_FILE.test(pathOf(url));
export const isMediaFile = (url: string) => isAudioFile(url) || VIDEO_FILE.test(pathOf(url));
export const isAudio = (url: string) => isAudioFile(url) || AUDIO_SITES.some((s) => siteOf(url).endsWith(s));
export const kindLabel = (v: Pick<VideoListItem, "kind" | "url"> & { source?: string | null; transcript_source?: string | null }) =>
  v.kind === "media" ? (isAudio(v.url) ? "Аудио" : "Видео") : (v.source ?? v.transcript_source) === "pdf" ? "PDF" : KIND_LABEL[v.kind];

// uploads a PDF, TXT or Markdown file; the result is a text material like pasted text
export async function uploadDocument(file: File, title?: string): Promise<VideoInfo> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  const res = await fetch("/api/videos/upload", { method: "POST", body: form });
  if (!res.ok) await fail(res);
  return res.json();
}
// the page can play it itself: YouTube through the embedded player, media files through <audio>/<video>
export const playable = (m: Pick<VideoListItem, "kind" | "url">) => m.kind === "youtube" || (m.kind === "media" && isMediaFile(m.url));

export function timeUrl(url: string, sec: number): string {
  const s = Math.floor(sec);
  try {
    const u = new URL(url);
    const site = u.hostname.replace(/^(www|m|player)\./, "");
    u.hash = "";
    if (site.endsWith("vimeo.com")) return `${u}#t=${s}s`;
    if (site.endsWith("dailymotion.com")) u.searchParams.set("start", String(s));
    else if (site.endsWith("rutube.ru")) u.searchParams.set("t", String(s));
    else if (site.endsWith("twitch.tv")) u.searchParams.set("t", `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60)}m${s % 60}s`);
    else if (isMediaFile(url)) return `${u}#t=${s}`;
    else return url;
    return String(u);
  } catch {
    return url;
  }
}

// "12:34" / "1:02:03" -> seconds, else null
export function clockSeconds(label: string): number | null {
  const m = label.trim().match(/^(?:(\d+):)?(\d{1,2}):(\d{2})$/);
  return m ? +(m[1] ?? 0) * 3600 + +m[2] * 60 + +m[3] : null;
}

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
  v.kind === "youtube" || v.kind === "media" ? minutes(v.duration_sec) : readingTime(v.word_count);

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
  if (m.kind === "media")
    return md.replace(/\[(\d{1,2}):(\d{2})(?::(\d{2}))?\](?!\()/g, (x, a, b, c) =>
      `[${x.slice(1, -1)}](${timeUrl(m.url, c ? +a * 3600 + +b * 60 + +c : +a * 60 + +b)})`);
  return md.replace(/\[¶(\d+)\](?!\()/g, (_, n) => `[абз. ${n}](${m.kind === "text" ? `#p${n}` : fragmentUrl(m.url, m.anchors?.[n])})`);
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

// "12,4 с" / "1 мин 5 с"
export function seconds(sec: number): string {
  if (sec >= 60) return `${Math.floor(sec / 60)} мин ${Math.round(sec % 60)} с`;
  return `${sec.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} с`;
}

const STEP_LABEL: [string, string][] = [
  ["transcript", "текст"],
  ["classify", "проверка"],
  ["summarize", "конспект"],
  ["keywords", "термины"],
  ["script", "сценарий"],
  ["critic", "редактор"],
  ["index", "индекс для вопросов"],
];
// the steps in the order they ran, with their times; the index is built in parallel with the summary
export const stepTimes = (m: Metrics) => STEP_LABEL.filter(([key]) => m.steps[key] !== undefined).map(([key, label]) => ({ label, time: seconds(m.steps[key]) }));
