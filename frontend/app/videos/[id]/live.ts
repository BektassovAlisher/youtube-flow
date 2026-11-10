"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, readNdjson, type Job, type VideoInfo } from "@/lib/api";

export type Failure = { kind: "process" | "script" | "audio"; stage: string | null; message: string };

// Live state of one video while its background jobs run: /api/videos/{id}/events streams the stages,
// the summary and the podcast script as they are written and audio progress. Reloading the page simply subscribes again.
export function useLive(id: string, initial: VideoInfo | null) {
  const [video, setVideo] = useState(initial);
  const [jobs, setJobs] = useState<Job[]>(initial?.jobs ?? []);
  const [partial, setPartial] = useState("");
  const [partialScript, setPartialScript] = useState("");
  const [failure, setFailure] = useState<Failure | null>(null);
  const [round, setRound] = useState(0); // bumped to (re)subscribe after starting a job
  const tokens = useRef("");
  const scriptTokens = useRef("");

  const refresh = useCallback(async () => {
    try {
      const v = await api<VideoInfo>(`videos/${id}`);
      setVideo(v);
      setJobs(v.jobs);
      return v;
    } catch {
      return null;
    }
  }, [id]);

  const watching = round > 0 || (initial?.jobs.length ?? 0) > 0 || initial?.status === "processing";

  useEffect(() => {
    if (!watching) return;
    const ctrl = new AbortController();
    // tokens arrive dozens per second: re-render the growing markdown a few times per second, not per token
    const flush = setInterval(() => {
      if (tokens.current) {
        const text = tokens.current;
        tokens.current = "";
        setPartial((p) => p + text);
      }
      if (scriptTokens.current) {
        const text = scriptTokens.current;
        scriptTokens.current = "";
        setPartialScript((p) => p + text);
      }
    }, 120);

    (async () => {
      const res = await fetch(`/api/videos/${id}/events`, { signal: ctrl.signal });
      if (!res.ok || !res.body) return;
      await readNdjson(res, (e) => {
        switch (e.type) {
          case "snapshot":
            setJobs(e.jobs);
            tokens.current = "";
            scriptTokens.current = "";
            setPartial(e.partial_summary ?? "");
            setPartialScript(e.partial_script ?? "");
            if (!e.jobs.length) refresh();
            break;
          case "job":
            setJobs((js) => [...js.filter((j) => j.kind !== e.kind), { kind: e.kind, status: e.status, stage: e.stage, done: e.done, total: e.total }]);
            break;
          case "token":
            if (e.kind === "script") scriptTokens.current += e.text;
            else tokens.current += e.text;
            break;
          case "restart": // the summary broke off mid-way, or the editor sent the script back: written again
            if (e.kind === "script") {
              scriptTokens.current = "";
              setPartialScript("");
            } else {
              tokens.current = "";
              setPartial("");
            }
            break;
          case "saved":
          case "rejected":
            refresh();
            break;
          case "done":
            setJobs((js) => js.filter((j) => j.kind !== e.kind));
            if (e.kind === "script") setPartialScript("");
            refresh();
            break;
          case "error":
            setJobs((js) => js.filter((j) => j.kind !== e.kind));
            setFailure({ kind: e.kind, stage: e.stage, message: e.message });
            if (e.kind === "script") {
              scriptTokens.current = "";
              setPartialScript("");
            } else {
              tokens.current = "";
              setPartial("");
            }
            refresh();
            break;
        }
      });
      // the stream ended: normally because nothing runs anymore; if a job still runs the connection broke — reconnect
      const v = await refresh();
      if (v?.jobs.length && !ctrl.signal.aborted) setTimeout(() => setRound((r) => r + 1), 2000);
    })().catch(() => {});

    return () => {
      clearInterval(flush);
      ctrl.abort();
    };
  }, [id, round, watching, refresh]);

  const follow = useCallback(() => {
    setFailure(null);
    setRound((r) => r + 1);
  }, []);

  return { video, setVideo, jobs, partial, partialScript, failure, follow };
}
