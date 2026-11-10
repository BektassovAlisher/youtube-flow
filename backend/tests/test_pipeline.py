import importlib
import logging
import threading

import config
import jobs
from agent import agent as nodes
from agent import agent_state
from db import cache as repo

VID = "AAAAAAAAAAA"
URL = f"https://www.youtube.com/watch?v={VID}"


def run(video_id=VID, force=False):
    job, created = jobs.start_processing(video_id, f"https://www.youtube.com/watch?v={video_id}", force)
    return job.future.result(timeout=30), created


def write_script(video_id=VID):
    """The «Написать сценарий» button."""
    job, _ = jobs.start_script(video_id)
    return job.future.result(timeout=30)


def test_new_video_full_pipeline(llm, youtube):
    events = []
    original = jobs.hub.emit
    jobs.hub.emit = lambda job, event: (events.append(event), original(job, event))[1]
    try:
        final, created = run()
    finally:
        jobs.hub.emit = original
    assert created and final == {"type": "done", "kind": "process"}

    video = repo.get_video(VID)
    assert video["status"] == "ready" and video["stage"] == "done" and video["error"] is None
    assert video["title"] == f"Лекция {VID}" and video["channel"] == "Канал"
    assert video["summary"].startswith("## Обзор лекции")
    assert video["keywords"][0] == "градиентный спуск"
    assert not video["podcast_script"]  # the podcast is written by a button
    assert video["indexed"] is True
    assert repo.load_transcript(VID)[0]["text"].startswith("фраза 0")

    assert llm.kinds() == ["classify", "summary", "keywords"]
    stages = [e["stage"] for e in events if "stage" in e]
    assert stages == ["transcript", "classify", "summary", "keywords"]
    tokens = "".join(e["token"] for e in events if "token" in e)
    assert tokens.strip() == video["summary"]  # the summary was streamed while it was written
    saved = [k for e in events for k in e if k.endswith("_saved")]
    assert saved == ["summary_saved"]

    assert write_script() == {"type": "done", "kind": "script"}
    assert repo.get_video(VID)["podcast_script"].startswith("Алекс:")


def test_classifier_sees_whole_video_and_keywords_come_from_summary(llm, youtube):
    run()
    prompts = dict(llm.calls)
    for label in ("[Начало]", "[Первая треть]", "[Середина]", "[Конец]"):
        assert label in prompts["classify"]
    assert "фраза 199" in prompts["classify"]  # the very end of the video
    # keywords are chosen from the summary's outline and bold terms, not from the transcript
    assert "Градиентный спуск (2)" in prompts["keywords"] and "фраза" not in prompts["keywords"]
    assert "Содержание раздела" not in prompts["keywords"]  # template labels are not terms


def test_every_text_task_uses_gemini_3_1_flash_lite():
    for model in (agent_state.gemini, agent_state.gemini_json, agent_state.gemini_backup):
        model.cache_clear()
    writer, checks = agent_state.gemini(), agent_state.gemini_json()
    assert config.GEMINI_MODEL == "gemini-3.1-flash-lite" and config.GEMINI_FALLBACK_MODEL is None
    for client in (writer, checks, agent_state.gemini_backup()):
        assert client.model.endswith("gemini-3.1-flash-lite") and client.max_retries == 6
    assert checks.response_mime_type == "application/json"
    assert writer.response_mime_type is None and writer.temperature is None
    assert not hasattr(agent_state, "groq_large") and not hasattr(agent_state, "checker")


def test_a_fallback_model_can_be_set(monkeypatch):
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
    try:
        importlib.reload(config)
        for model in (agent_state.gemini, agent_state.gemini_backup):
            model.cache_clear()
        chain = agent_state.gemini()
        assert chain.runnable.model.endswith("gemini-3.1-flash-lite") and chain.runnable.max_retries == 2
        assert chain.fallbacks[0].model.endswith("gemini-2.5-flash") and chain.fallbacks[0].max_retries == 6
        assert agent_state.gemini_backup().model.endswith("gemini-2.5-flash")
    finally:
        monkeypatch.undo()
        importlib.reload(config)
        agent_state.gemini.cache_clear()
        agent_state.gemini_backup.cache_clear()


def test_model_settings_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "")  # docker compose passes unset variables as empty strings
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "fast")
    try:
        importlib.reload(config)
        assert config.GEMINI_MODEL == "gemini-3.1-flash-lite" and config.GEMINI_THINKING_LEVEL is None
        monkeypatch.setenv("GEMINI_THINKING_LEVEL", "Low")
        importlib.reload(config)
        assert config.GEMINI_THINKING_LEVEL == "low"
        agent_state.gemini.cache_clear()
        assert agent_state.gemini().thinking_level == "low"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
        agent_state.gemini.cache_clear()


def test_critic_reads_the_whole_script(llm):
    script = "Алекс: " + "очень длинная реплика про градиентный спуск. " * 400  # ~18,000 characters
    nodes.critic_node({"podcast_script": script, "keywords": ["градиентный спуск"]})
    kind, prompt = llm.calls[-1]
    assert kind == "critic" and "[текст обрезан]" not in prompt and prompt.count("очень длинная") == 400


def test_json_answers_are_read_leniently():
    assert nodes._parse_json('```json\n["нейрон", "вес"]\n```', list) == ["нейрон", "вес"]
    assert nodes._parse_json('{"keywords": ["нейрон", "вес"]}', list) == ["нейрон", "вес"]
    assert nodes._parse_json('Вот ответ: {"is_valid": true}', dict) == {"is_valid": True}
    assert nodes._parse_json('{"keywords": "нейрон"}', list) is None


def test_processing_time_is_logged(llm, youtube, caplog):
    caplog.set_level(logging.INFO, logger="jobs")
    run()
    write_script()
    process, script = [r.getMessage() for r in caplog.records if "готово за" in r.getMessage()]
    for step in ("transcript", "classify", "summarize", "keywords"):
        assert f"{step} " in process
    for step in ("script", "critic"):
        assert f"{step} " in script


def test_a_failed_script_keeps_the_material_and_can_be_retried(llm, youtube):
    run()
    llm.fail["script"] = RuntimeError("429 Resource exhausted")
    final = write_script()
    assert final["type"] == "error" and final["kind"] == "script" and final["stage"] == "script"
    assert "лимит" in final["message"]

    video = repo.get_video(VID)
    assert video["status"] == "ready" and video["error"] is None  # the material itself is fine
    assert video["summary"] and video["keywords"] and not video["podcast_script"]

    llm.fail.clear()
    llm.calls.clear()
    youtube["transcript"] = 0
    assert write_script()["type"] == "done"
    assert llm.kinds() == ["script", "critic"]  # nothing else done twice
    assert youtube["transcript"] == 0
    assert repo.get_video(VID)["podcast_script"]


def test_critic_rejection_rewrites_the_script_once(llm, youtube):
    llm.critic_verdicts = ['{"is_valid": false, "feedback": "мало терминов"}', '{"is_valid": true, "feedback": "ok"}']
    run()
    events = []
    original = jobs.hub.emit
    jobs.hub.emit = lambda job, event: (events.append(event), original(job, event))[1]
    try:
        write_script()
    finally:
        jobs.hub.emit = original
    assert sum(1 for e in events if e.get("restart")) == 1  # the page drops the first version
    kinds = llm.kinds()
    assert kinds.count("script") == 2 and kinds.count("critic") == 2
    second_script_prompt = [p for k, p in llm.calls if k == "script"][1]
    assert "мало терминов" in second_script_prompt


def test_educational_youtube_category_skips_the_model(llm, youtube):
    youtube["category"] = "Education"
    final, _ = run()
    assert final["type"] == "done" and "classify" not in llm.kinds()
    c = repo.get_video(VID)["classification"]
    assert c["is_suitable"] and c["category"] == "educational" and "Образование" in c["reason"]


def test_other_youtube_category_is_a_hint_for_the_model(llm, youtube):
    youtube["category"] = "Music"
    run()
    assert "Категория на YouTube (выбирает автор, бывает неточной): Music" in dict(llm.calls)["classify"]


def test_category_is_read_from_the_watch_page(monkeypatch):
    from tools import youtube_scraper as yt

    class Page:
        ok = True
        text = '<html><meta itemprop="genre" content="Science &amp; Technology"></html>'

    monkeypatch.setattr(yt.requests, "get", lambda *a, **kw: Page())
    assert yt.fetch_category(VID) == "Science & Technology"
    Page.text = '..."category":"Education","publishDate"...'
    assert yt.fetch_category(VID) == "Education"
    Page.text = "<html>consent page</html>"
    assert yt.fetch_category(VID) is None

    def offline(*a, **kw):
        raise yt.requests.ConnectionError("no network")

    monkeypatch.setattr(yt.requests, "get", offline)
    assert yt.fetch_category(VID) is None


def test_rejected_video_and_processing_anyway(llm, youtube):
    llm.classification = '{"category": "music", "is_suitable": false, "confidence": 0.9, "reason": "клип"}'
    final, _ = run()
    assert final["type"] == "done"
    video = repo.get_video(VID)
    assert video["status"] == "rejected" and video["classification"]["reason"] == "клип"
    assert not video["summary"] and "summary" not in llm.kinds()

    llm.calls.clear()
    run(force=True)
    video = repo.get_video(VID)
    assert video["status"] == "ready" and video["summary"] and video["force"] is True
    assert "classify" not in llm.kinds()  # the stored verdict is kept, only overridden


def test_same_video_twice_runs_once(llm, youtube):
    gate = threading.Event()
    original = llm.stream

    def slow_stream(prompt):
        gate.wait(5)
        yield from original(prompt)

    llm.stream = slow_stream
    first, created1 = jobs.start_processing(VID, URL)
    second, created2 = jobs.start_processing(VID, URL)
    gate.set()
    first.future.result(timeout=30)
    assert created1 and not created2 and first is second
    assert llm.kinds().count("summary") == 1 and youtube["transcript"] == 1


def test_interrupted_runs_resume_on_startup(llm, youtube):
    run()
    repo.clear_for_regenerate(VID, "summary")
    repo.set_stage(VID, "summary")  # as if the API was restarted in the middle of the summary
    llm.calls.clear()
    assert jobs.resume_interrupted() == 1
    jobs.hub.wait(VID, "process", timeout=30)
    assert llm.kinds() == ["summary", "keywords"]
    assert repo.get_video(VID)["stage"] == "done"


def test_transcript_error_is_reported(llm, youtube, monkeypatch):
    import agent.agent as nodes
    from errors import UserError

    def no_video(video_id):
        raise UserError("Видео недоступно: оно удалено, скрыто или в ссылке ошибка.")

    monkeypatch.setattr(nodes, "get_transcript", no_video)
    final, _ = run()
    assert final == {"type": "error", "kind": "process", "stage": "transcript",
                     "message": "Видео недоступно: оно удалено, скрыто или в ссылке ошибка."}
    video = repo.get_video(VID)
    assert video["status"] == "failed" and video["error"].startswith("Видео недоступно")


class Overloaded(Exception):
    pass


def test_overloaded_summary_is_retried_and_the_page_starts_over(llm, youtube, monkeypatch):
    monkeypatch.setattr(nodes.time, "sleep", lambda s: None)
    real = llm.stream
    calls = {"n": 0}

    def stream(prompt):  # the first stream breaks after a few chunks, like Gemini's "503 high demand"
        if llm._kind(str(prompt)) == "summary" and calls["n"] == 0:
            calls["n"] += 1
            yield from list(real(prompt))[:3]
            raise Overloaded("503 UNAVAILABLE. This model is currently experiencing high demand.")
        yield from real(prompt)

    monkeypatch.setattr(llm, "stream", stream)
    events = []
    original = jobs.hub.emit
    jobs.hub.emit = lambda job, event: (events.append(event), original(job, event))[1]
    try:
        final, _ = run()
    finally:
        jobs.hub.emit = original
    assert final == {"type": "done", "kind": "process"}
    assert repo.get_video(VID)["summary"].startswith("## Обзор лекции")
    assert any(e.get("restart") for e in events)
    after = events[[i for i, e in enumerate(events) if e.get("restart")][0] + 1:]
    assert "".join(e["token"] for e in after if "token" in e).strip() == repo.get_video(VID)["summary"]


def test_not_overloaded_errors_are_not_retried(llm, youtube, monkeypatch):
    monkeypatch.setattr(nodes.time, "sleep", lambda s: None)
    llm.fail["summary"] = ValueError("bad request")
    final, _ = run()
    assert final["type"] == "error" and final["stage"] == "summary"


def test_overload_message_is_clear():
    from errors import humanize
    assert "перегружена" in humanize(Overloaded("503 UNAVAILABLE. high demand"))


def test_metrics_are_saved_per_step_with_tokens(llm, youtube):
    run()
    m = repo.get_video(VID)["metrics"]
    assert {"transcript", "classify", "summarize", "keywords", "index"} == set(m["steps"])
    assert m["seconds"] >= max(m["steps"].values()) and m["first_token"] >= 0 and m["runs"] == 1
    # classify and keywords: 100 in and 20 out each; the streamed summary: 1000 in and 300 out
    assert m["tokens"] == {"input": 1200, "output": 340} and m["model"] == "gemini-3.1-flash-lite"

    write_script()  # the streamed script 1000 and 300, its critic 100 and 20: added to the same material
    m = repo.get_video(VID)["metrics"]
    assert {"script", "critic"} <= set(m["steps"]) and m["runs"] == 2
    assert m["tokens"] == {"input": 2300, "output": 660}

    stats = repo.stats()
    assert stats["materials"] == 1 and stats["tokens"] == {"input": 2300, "output": 660}
    assert stats["avg_steps"]["summarize"] == m["steps"]["summarize"]


def test_metrics_of_a_resumed_run_add_up(llm, youtube):
    llm.fail["summary"] = ValueError("bad request")  # not an overload: the run stops at the summary
    run()
    first = repo.get_video(VID)["metrics"]
    assert "classify" in first["steps"] and "summarize" not in first["steps"]
    llm.fail.clear()
    run()  # only the summary and the terms are left
    m = repo.get_video(VID)["metrics"]
    assert m["runs"] == 2 and m["steps"]["classify"] == first["steps"]["classify"] and "summarize" in m["steps"]
    assert m["tokens"]["input"] == 1200 and m["seconds"] >= first["seconds"]
