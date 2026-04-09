from db.database import SessionLocal, Video, Summary, Keyword, PodcastScript


def get_cached_video(video_id: str) -> dict | None:
   
    session = SessionLocal()
    try:
        video = session.query(Video).filter(Video.video_id == video_id).first()
        if not video:
            return None

        summary = session.query(Summary).filter(Summary.video_id == video_id).first()
        keywords = session.query(Keyword).filter(Keyword.video_id == video_id).all()
        script = session.query(PodcastScript).filter(PodcastScript.video_id == video_id).first()

        return {
            "video_id": video.video_id,
            "language": video.language,
            "summary": summary.content if summary else "",
            "keywords": [k.keyword for k in keywords],
            "podcast_script": script.script if script else "",
        }
    finally:
        session.close()


def save_to_cache(
    video_id: str,
    url: str,
    language: str,
    duration_sec: float,
    summary: str,
    keywords: list[str],
    script: str,
):
    """Сохраняет все результаты в БД"""
    session = SessionLocal()
    try:
        # сохраняем видео
        video = Video(
            video_id=video_id,
            url=url,
            language=language,
            duration_sec=duration_sec,
        )
        session.merge(video)
        session.flush()  

        session.add(Summary(video_id=video_id, content=summary))

        for kw in keywords:
            session.add(Keyword(video_id=video_id, keyword=kw))

        session.add(PodcastScript(video_id=video_id, script=script))

        session.commit()
        print(f"✅ Сохранено в БД: {video_id}")

    except Exception as e:
        session.rollback()
        print(f"🚨 Ошибка сохранения в БД: {e}")
    finally:
        session.close()