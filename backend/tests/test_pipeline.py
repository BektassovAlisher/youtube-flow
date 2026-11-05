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
    assert video["podcast_script"].startswith("Алекс:")
    assert video["indexed"] is True
    assert repo.load_transcript(VID)[0]["text"].startswith("фраза 0")

    assert llm.kinds() == ["classify", "summary", "keywords", "script", "critic"]
    stages = [e["stage"] for e in events if "stage" in e]
    assert stages == ["transcript", "classify", "summary", "keywords", "script"]
    tokens = "".join(e["token"] for e in events if "token" in e)
    assert tokens.strip() == video["summary"]  # the summary was streamed while it was written
    saved = [k for e in events for k in e if k.endswith("_saved")]
    assert saved == ["summary_saved", "script_saved"]


def test_classifier_sees_whole_video_and_keywords_come_from_summary(llm, youtube):
    run()
    prompts = dict(llm.calls)
    for label in ("[Начало]", "[Первая треть]", "[Середина]", "[Конец]"):
        assert label in prompts["classify"]
    assert "фраза 199" in prompts["classify"]  # the very end of the video
    # keywords are chosen from the summary's outline and bold terms, not from the transcript
    assert "Градиентный спуск (2)" in prompts["keywords"] and "фраза" not in prompts["keywords"]
    assert "Содержание раздела" not in prompts["keywords"]  # template labels are not terms


def test_groq_models_are_deterministic():
    agent_state.groq_small.cache_clear()
    agent_state.groq_large.cache_clear()
    # langchain-groq sends 0 as 1e-8 (the Groq API quirk), which is greedy decoding all the same
    assert agent_state.groq_small().temperature < 1e-6
    assert agent_state.groq_large().temperature < 1e-6


def test_checks_go_to_gemini_unless_groq_is_chosen(monkeypatch):
    for model in (agent_state.gemini, agent_state.gemini_json, agent_state.groq_small, agent_state.groq_large):
        model.cache_clear()
    checker = agent_state.checker("small")
    assert checker is agent_state.gemini_json() and checker.response_mime_type == "application/json"
    writer = agent_state.gemini()
    assert writer.response_mime_type is None and writer.max_retries == 6 and writer.temperature is None

    monkeypatch.setattr(config, "CHECKS_PROVIDER", "groq")
    assert agent_state.checker("small") is agent_state.groq_small()
    assert agent_state.checker() is agent_state.groq_large()


def test_model_settings_from_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "")  # docker compose passes unset variables as empty strings
    monkeypatch.setenv("CHECKS_PROVIDER", " Groq ")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "fast")
    try:
        importlib.reload(config)
        assert config.GEMINI_MODEL == "gemini-3.5-flash-lite"
        assert config.CHECKS_PROVIDER == "groq" and config.GEMINI_THINKING_LEVEL is None
        monkeypatch.setenv("GEMINI_THINKING_LEVEL", "Low")
        monkeypatch.setenv("CHECKS_PROVIDER", "openai")
        importlib.reload(config)
        assert config.GEMINI_THINKING_LEVEL == "low" and config.CHECKS_PROVIDER == "gemini"
        agent_state.gemini.cache_clear()
        assert agent_state.gemini().thinking_level == "low"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
        agent_state.gemini.cache_clear()


def test_critic_reads_the_whole_script_unless_groq_checks_it(llm, monkeypatch):
    script = "Алекс: " + "очень длинная реплика про градиентный спуск. " * 400  # ~18,000 characters
    nodes.critic_node({"podcast_script": script, "keywords": ["градиентный спуск"]})
    kind, prompt = llm.calls[-1]
    assert kind == "critic" and "[текст обрезан]" not in prompt and prompt.count("очень длинная") == 400

    monkeypatch.setattr(config, "CHECKS_PROVIDER", "groq")  # Groq's free tier counts tokens per minute
    nodes.critic_node({"podcast_script": script, "keywords": ["градиентный спуск"]})
    assert "[текст обрезан]" in llm.calls[-1][1]


def test_json_answers_are_read_leniently():
    assert nodes._parse_json('```json\n["нейрон", "вес"]\n```', list) == ["нейрон", "вес"]
    assert nodes._parse_json('{"keywords": ["нейрон", "вес"]}', list) == ["нейрон", "вес"]
    assert nodes._parse_json('Вот ответ: {"is_valid": true}', dict) == {"is_valid": True}
    assert nodes._parse_json('{"keywords": "нейрон"}', list) is None


def test_processing_time_is_logged(llm, youtube, caplog):
    caplog.set_level(logging.INFO, logger="jobs")
    run()
    line = next(r.getMessage() for r in caplog.records if "готово за" in r.getMessage())
    for step in ("transcript", "classify", "summarize", "keywords", "script", "critic"):
        assert f"{step} " in line


def test_summary_survives_a_failed_script_and_the_retry_resumes(llm, youtube):
    llm.fail["script"] = RuntimeError("429 Resource exhausted")
    final, _ = run()
    assert final["type"] == "error" and final["stage"] == "script"
    assert "лимит" in final["message"]

    video = repo.get_video(VID)
    assert video["status"] == "ready"  # the summary is there and readable
    assert video["summary"] and video["keywords"] and not video["podcast_script"]
    assert video["error"] == final["message"]

    llm.calls.clear()
    youtube["transcript"] = 0
    final, _ = run()
    assert final["type"] == "done"
    assert llm.kinds() == ["script", "critic"]  # nothing done twice
    assert youtube["transcript"] == 0  # the stored transcript was reused
    assert repo.get_video(VID)["podcast_script"]


def test_critic_rejection_rewrites_the_script_once(llm, youtube):
    llm.critic_verdicts = ['{"is_valid": false, "feedback": "мало терминов"}', '{"is_valid": true, "feedback": "ok"}']
    run()
    kinds = llm.kinds()
    assert kinds.count("script") == 2 and kinds.count("critic") == 2
    second_script_prompt = [p for k, p in llm.calls if k == "script"][1]
    assert "мало терминов" in second_script_prompt


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
    repo.clear_for_regenerate(VID, "script")
    repo.set_stage(VID, "script")  # as if the API was restarted in the middle of the script
    llm.calls.clear()
    assert jobs.resume_interrupted() == 1
    jobs.hub.wait(VID, "process", timeout=30)
    assert llm.kinds() == ["script", "critic"]
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
