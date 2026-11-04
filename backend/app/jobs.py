"""Background work: at most one job per (video, kind), a bounded worker pool, live events for open pages.

The HTTP request that starts a job returns at once; the work goes on even if the tab is closed or reloaded,
and every open page of that video receives the same progress (stages, summary tokens, audio progress)."""
import asyncio
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

import config
from errors import UserError, humanize

log = logging.getLogger(__name__)

PING_SECONDS = 15


@dataclass
class Job:
    video_id: str
    kind: str  # "process" | "audio"
    status: str = "queued"  # queued | running
    stage: str | None = None
    done: int = 0
    total: int = 0
    rejected: bool = False
    tokens: list[str] = field(default_factory=list)  # the summary as it is being written
    future: Future | None = None

    def snapshot(self) -> dict:
        return {"kind": self.kind, "status": self.status, "stage": self.stage, "done": self.done, "total": self.total}


class Hub:
    def __init__(self, workers: int):
        self._workers = workers
        self._lock = threading.Lock()
        self._jobs: dict[tuple[str, str], Job] = {}
        self._subscribers: dict[str, set] = {}
        self._pool: ThreadPoolExecutor | None = None

    def _executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(self._workers, thread_name_prefix="job")
            return self._pool

    # -- jobs ------------------------------------------------------------------------------------

    def get(self, video_id: str, kind: str) -> Job | None:
        with self._lock:
            return self._jobs.get((video_id, kind))

    def active(self, video_id: str) -> list[dict]:
        with self._lock:
            return [j.snapshot() for (v, _), j in self._jobs.items() if v == video_id]

    def submit(self, video_id: str, kind: str, work: Callable[[Job], None]) -> tuple[Job, bool]:
        """Starts `work` in the pool unless the same job is already queued or running."""
        pool = self._executor()
        with self._lock:  # other threads see the job only together with its future
            job = self._jobs.get((video_id, kind))
            if job is not None:
                return job, False
            job = Job(video_id, kind)
            self._jobs[(video_id, kind)] = job
            self._send(video_id, {"type": "job", **job.snapshot()})
            job.future = pool.submit(self._run, job, work)
        return job, True

    def _run(self, job: Job, work: Callable[[Job], None]) -> dict:
        self.emit(job, {"status": "running"})
        final = {"type": "done", "kind": job.kind}
        try:
            work(job)
        except Exception as e:  # noqa: BLE001
            if isinstance(e, UserError):
                log.warning("%s/%s: %s", job.video_id, job.kind, e.message)
            else:
                log.exception("%s/%s упал", job.video_id, job.kind)
            final = {"type": "error", "kind": job.kind, "stage": job.stage, "message": humanize(e)}
        finally:
            with self._lock:
                self._jobs.pop((job.video_id, job.kind), None)
                self._send(job.video_id, final)
        return final

    def wait(self, video_id: str, kind: str, timeout: float | None = None) -> dict | None:
        job = self.get(video_id, kind)
        return job.future.result(timeout) if job and job.future else None

    def shutdown(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool:
            pool.shutdown(wait=False, cancel_futures=True)

    # -- events ----------------------------------------------------------------------------------

    # Events are sent while holding the lock: every page receives them in the order they happened,
    # and after the snapshot it got when subscribing. Sending only queues a callback, so it is cheap.

    def emit(self, job: Job, event: dict) -> None:
        """Called from the worker thread with what the graph or the audio generator reports."""
        out = []
        with self._lock:
            if "status" in event:
                job.status = event["status"]
                out.append({"type": "job", **job.snapshot()})
            if "stage" in event:
                job.stage = event["stage"]
                out.append({"type": "job", **job.snapshot()})
            if "progress" in event:
                job.done, job.total = event["progress"]
                out.append({"type": "job", **job.snapshot()})
            if "token" in event:
                job.tokens.append(event["token"])
                out.append({"type": "token", "text": event["token"]})
            for what in ("summary", "script", "audio", "meta"):
                if event.get(f"{what}_saved") or (what == "meta" and "meta" in event):
                    if what == "summary":
                        job.tokens.clear()  # it is in the database now
                    out.append({"type": "saved", "what": what})
            if "rejected" in event:
                job.rejected = True
                out.append({"type": "rejected", "classification": event["rejected"]})
            for e in out:
                self._send(job.video_id, e)

    def _send(self, video_id: str, event: dict) -> None:
        """Caller holds the lock."""
        for loop, queue in self._subscribers.get(video_id, ()):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # the page went away together with its event loop
                pass

    async def events(self, video_id: str) -> AsyncIterator[dict]:
        """A snapshot of the running jobs, then live events until no job for the video is left."""
        subscriber = (asyncio.get_running_loop(), asyncio.Queue())
        with self._lock:
            jobs = [j for (v, _), j in self._jobs.items() if v == video_id]
            process = next((j for j in jobs if j.kind == "process"), None)
            snapshot = {"type": "snapshot", "jobs": [j.snapshot() for j in jobs],
                        "partial_summary": "".join(process.tokens) if process else ""}
            if jobs:
                self._subscribers.setdefault(video_id, set()).add(subscriber)
        try:
            yield snapshot
            if not jobs:
                yield {"type": "idle"}
                return
            while True:
                try:
                    event = await asyncio.wait_for(subscriber[1].get(), timeout=PING_SECONDS)
                except asyncio.TimeoutError:
                    yield {"type": "ping"}  # keeps proxies from closing a quiet connection
                    continue
                yield event
                if event["type"] in ("done", "error") and not self.active(video_id):
                    yield {"type": "idle"}
                    return
        finally:
            with self._lock:
                subs = self._subscribers.get(video_id)
                if subs:
                    subs.discard(subscriber)
                    if not subs:
                        self._subscribers.pop(video_id, None)


hub = Hub(config.MAX_CONCURRENT_JOBS)


# ---- the two kinds of work --------------------------------------------------------------------

def start_processing(video_id: str, url: str, force: bool = False, kind: str | None = None) -> tuple[Job, bool]:
    """`kind` only matters for a new material; an existing one keeps its own."""
    from agent.agent_node import app as graph, initial_state
    from db import cache as repo

    if hub.get(video_id, "process") is None:
        repo.begin_processing(video_id, url, force, kind)

    def work(job: Job) -> None:
        try:
            for mode, payload in graph.stream(initial_state(video_id, force), stream_mode=["custom", "updates"]):
                if mode == "custom":
                    hub.emit(job, payload)
            if not job.rejected:
                repo.finish(video_id)
        except Exception as e:
            repo.fail(video_id, humanize(e))
            raise

    return hub.submit(video_id, "process", work)


def start_audio(video_id: str, script: str) -> tuple[Job, bool]:
    from db import cache as repo
    from tools.audio_generator import generate_podcast_audio

    def work(job: Job) -> None:
        audio = generate_podcast_audio(script, on_progress=lambda d, t: hub.emit(job, {"progress": (d, t)}))
        repo.save_audio(video_id, audio)
        hub.emit(job, {"audio_saved": True})

    return hub.submit(video_id, "audio", work)


def resume_interrupted() -> int:
    """Runs cut off by a restart continue from their last saved step."""
    from db import cache as repo

    pending = repo.interrupted()
    for v in pending:
        start_processing(v["video_id"], v["url"], v["force"])
    if pending:
        log.info("возобновлено обработок: %d", len(pending))
    return len(pending)
