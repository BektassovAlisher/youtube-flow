export type VideoListItem = {
  video_id: string;
  title: string | null;
  url: string;
  language: string | null;
  duration_sec: number | null;
  category: string | null;
  created_at: string | null;
};

export type VideoInfo = {
  video_id: string;
  title: string | null;
  summary: string;
  keywords: string[];
  podcast_script: string;
  language: string;
  category: string | null;
};

export type GenerateResult = {
  video_id: string;
  rejected: boolean;
  video_category: string | null;
  classification_reason: string | null;
};

export type Link = { title: string; url: string };
export type Recs = { courses: Link[]; books: Link[]; from_cache: boolean };
export type Answer = { answer: string; sources: { timestamp: string; url: string }[] };

// Browser talks to /api/*, which app/api/[...path]/route.ts forwards to FastAPI.
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/${path}`, { ...init, headers: { "content-type": "application/json" } });
  if (!res.ok) await fail(res);
  return res.json();
}

export async function fail(res: Response): Promise<never> {
  const body = await res.json().catch(() => null);
  throw new Error(typeof body?.detail === "string" ? body.detail : `Ошибка ${res.status}`);
}

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
