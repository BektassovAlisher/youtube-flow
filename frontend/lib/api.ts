export type VideoStatus = "processing" | "ready" | "rejected" | "failed";

export type VideoListItem = {
  video_id: string;
  title: string | null;
  url: string;
  language: string | null;
  duration_sec: number | null;
  category: string | null;
  channel: string | null;
  status: VideoStatus;
  created_at: string | null;
};

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

// pipeline stages as the API reports them (job.stage)
export const STAGES = [
  ["transcript", "Получаю субтитры"],
  ["classify", "Проверяю, что это обучающее видео"],
  ["summary", "Пишу конспект"],
  ["keywords", "Выделяю ключевые термины"],
  ["script", "Пишу сценарий подкаста — редактор проверяет"],
] as const;

export const CATEGORY: Record<string, string> = {
  educational: "Образование",
  entertainment: "Развлечения",
  news: "Новости",
  music: "Музыка",
  gaming: "Игры",
  random: "Разное",
  unknown: "Без категории",
};

export function addedOn(createdAt: string | null): string | null {
  if (!createdAt) return null;
  const utc = /Z|[+-]\d\d:\d\d$/.test(createdAt) ? createdAt : createdAt + "Z"; // API sends naive UTC
  return new Date(utc).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export const thumb = (id: string, size = "mqdefault") => `https://img.youtube.com/vi/${id}/${size}.jpg`;

export const minutes = (sec: number | null) => (sec ? `${Math.round(sec / 60)} мин` : null);

// "[12:34]" / "[1:02:03]" -> markdown link to that moment of the video
export function linkTimestamps(md: string, videoId: string): string {
  return md.replace(/\[(\d{1,2}):(\d{2})(?::(\d{2}))?\](?!\()/g, (m, a, b, c) => {
    const sec = c ? +a * 3600 + +b * 60 + +c : +a * 60 + +b;
    return `[${m.slice(1, -1)}](https://youtu.be/${videoId}?t=${sec})`;
  });
}

// seconds of a youtu.be/<id>?t=<sec> link to this very video, else null
export function seekTarget(href: string | undefined, videoId: string): number | null {
  const m = href?.match(/^https:\/\/youtu\.be\/([\w-]{11})\?t=(\d+)$/);
  return m && m[1] === videoId ? +m[2] : null;
}
