"""Background work: at most one job per (video, kind), a bounded worker pool, live events for open pages.

The HTTP request that starts a job returns at once; the work goes on even if the tab is closed or reloaded,
and every open page of that video receives the same progress (stages, summary tokens, audio progress)."""
import asyncio
import logging
import threading
import time
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
    kind: str  # "process" | "script" | "audio"
    status: str = "queued"  # queued | running
    stage: str | None = None
    done: int = 0
    total: int = 0
    rejected: bool = False
    tokens: list[str] = field(default_factory=list)  # the summary or the script as it is being written
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
            if event.get("restart"):  # the text starts over (a broken stream, a script the editor sent back)
                job.tokens.clear()
                out.append({"type": "restart", "kind": job.kind})
            if "token" in event:
                job.tokens.append(event["token"])
                out.append({"type": "token", "kind": job.kind, "text": event["token"]})
            for what in ("summary", "script", "audio", "meta"):
                if event.get(f"{what}_saved") or (what == "meta" and "meta" in event):
                    if what in ("summary", "script"):
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
            partial = {j.kind: "".join(j.tokens) for j in jobs}
            snapshot = {"type": "snapshot", "jobs": [j.snapshot() for j in jobs],
                        "partial_summary": partial.get("process", ""), "partial_script": partial.get("script", "")}
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


# ---- the three kinds of work ------------------------------------------------------------------

def _run_graph(job: Job, graph, state: dict, trace: dict) -> None:
    """Runs a graph, passes its events to the pages and saves how long each step took and the tokens."""
    from db import cache as repo

    started, marks = time.monotonic(), []
    run: dict = {"steps": {}, "tokens": {"input": 0, "output": 0}, "model": config.GEMINI_MODEL}
    try:
        for mode, payload in graph.stream(state, trace, stream_mode=["custom", "updates"]):
            if mode == "custom":
                for step, seconds in (payload.get("timing") or {}).items():
                    if step == "first_token":
                        run["first_token"] = seconds
                    else:  # the script and its critic can run more than once
                        run["steps"][step] = round(run["steps"].get(step, 0) + seconds, 2)
                for name, n in (payload.get("usage") or {}).items():
                    run["tokens"][name] += n
                hub.emit(job, payload)
            else:  # a step finished: when, counting from the start (steps already saved do nothing)
                marks += [f"{step} {time.monotonic() - started:.1f}" for step, update in payload.items() if update]
    finally:  # a failed run counts too: the retry only does what is left, and the numbers add up
        run["seconds"] = round(time.monotonic() - started, 2)
        if run["steps"]:
            repo.add_metrics(job.video_id, run)
            hub.emit(job, {"meta": True})  # pages reload the material and show the numbers
    log.info("%s/%s: готово за %.1f с; шаги закончились на секунде: %s; токены: %d на входе, %d на выходе",
             job.video_id, job.kind, run["seconds"], ", ".join(marks) or "—", run["tokens"]["input"], run["tokens"]["output"])


def start_processing(video_id: str, url: str, force: bool = False, kind: str | None = None) -> tuple[Job, bool]:
    """Everything up to the key terms. `kind` only matters for a new material; an existing one keeps its own."""
    from agent.agent_node import app as graph, initial_state
    from db import cache as repo

    if hub.get(video_id, "process") is None:
        repo.begin_processing(video_id, url, force, kind)

    def work(job: Job) -> None:
        # in LangSmith (when tracing is on) the whole run is one trace, found by the material's id
        trace = {"run_name": "VideoFlow: обработка материала", "tags": ["process"], "metadata": {"video_id": video_id}}
        try:
            _run_graph(job, graph, initial_state(video_id, force), trace)
            if not job.rejected:
                repo.finish(video_id)
        except Exception as e:
            repo.fail(video_id, humanize(e))
            raise

    return hub.submit(video_id, "process", work)


def start_script(video_id: str) -> tuple[Job, bool]:
    """The podcast script, by a button: the scriptwriter and the editor, from the saved summary and terms."""
    from agent.agent_node import script_app, script_state
    from db import cache as repo

    def work(job: Job) -> None:
        video = repo.get_video(video_id)
        if not video or not video["summary"]:
            raise UserError("Сценарий пишется по конспекту, а его ещё нет.", status=409)
        trace = {"run_name": "VideoFlow: сценарий подкаста", "tags": ["script"], "metadata": {"video_id": video_id}}
        _run_graph(job, script_app, script_state(video), trace)

    return hub.submit(video_id, "script", work)


def start_audio(video_id: str, script: str) -> tuple[Job, bool]:
    from db import cache as repo
    from tools.audio_generator import generate_podcast_audio

    def work(job: Job) -> None:
        started = time.monotonic()
        audio = generate_podcast_audio(script, on_progress=lambda d, t: hub.emit(job, {"progress": (d, t)}))
        repo.save_audio(video_id, audio)
        seconds = round(time.monotonic() - started, 2)
        repo.add_metrics(video_id, {"audio": seconds})
        hub.emit(job, {"audio_saved": True})
        log.info("%s: аудио готово за %.1f с", video_id, seconds)

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
