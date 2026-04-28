from datetime import datetime, timedelta
from .database import SessionLocal, Video, Summary, Keyword, PodcastScript, PodcastAudio, Recommendation
from agent.chat_agent.rag import delete_video_index



def is_expired(created_at: datetime, days: int = 7) -> bool:
    return datetime.utcnow() - created_at > timedelta(days=days)


def _delete_children(session, video_id: str, delete_index: bool = True):
   
    session.query(Summary).filter(Summary.video_id == video_id).delete()
    session.query(Keyword).filter(Keyword.video_id == video_id).delete()
    session.query(PodcastScript).filter(PodcastScript.video_id == video_id).delete()
    session.query(PodcastAudio).filter(PodcastAudio.video_id == video_id).delete()
    session.query(Recommendation).filter(Recommendation.video_id == video_id).delete()
    
    if delete_index:
        delete_video_index(video_id)


def get_cached_video(video_id: str, ttl_days: int = 7) -> dict | None:
    session = SessionLocal()
    try:
        video = session.query(Video).filter(Video.video_id == video_id).first()
        if not video:
            return None

        if is_expired(video.created_at, days=ttl_days):
            print(f"⏰ Кэш устарел: {video_id} — удаляем")
            _delete_children(session, video_id)
            session.delete(video)
            session.commit()
            return None

        summary  = session.query(Summary).filter(Summary.video_id == video_id).first()
        keywords = session.query(Keyword).filter(Keyword.video_id == video_id).all()
        script   = session.query(PodcastScript).filter(PodcastScript.video_id == video_id).first()
        rec      = session.query(Recommendation).filter(Recommendation.video_id == video_id).first()

        return {
            "video_id":       video.video_id,
            "title":          video.title,
            "language":       video.language,
            "category":       video.category,
            "summary":        summary.content if summary else "",
            "keywords":       [k.keyword for k in keywords],
            "podcast_script": script.script if script else "",
            "recommendation": rec.data if rec else None,
        }
    finally:
        session.close()


def get_cached_audio(video_id: str) -> bytes | None:
    session = SessionLocal()
    try:
        audio = session.query(PodcastAudio).filter(
            PodcastAudio.video_id == video_id
        ).first()
        return audio.audio_data if audio else None
    finally:
        session.close()


def get_cached_recommendation(video_id: str) -> dict | None:
    """Return cached {courses, books} dict or None."""
    session = SessionLocal()
    try:
        rec = session.query(Recommendation).filter(Recommendation.video_id == video_id).first()
        return rec.data if rec else None
    finally:
        session.close()


def save_to_cache(
    video_id: str,
    title: str,
    url: str,
    language: str,
    duration_sec: float,
    summary: str,
    keywords: list[str],
    script: str,
    category: str = None,
):
    session = SessionLocal()
    try:
        session.merge(Video(
            video_id=video_id,
            title=title,
            url=url,
            language=language,
            duration_sec=duration_sec,
            category=category,
        ))

        _delete_children(session, video_id, delete_index=False)
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


def save_recommendation_to_cache(video_id: str, recommendation: dict):
    session = SessionLocal()
    try:
        # Guard: recommendation has a FK on videos.video_id
        video_exists = session.query(Video).filter(Video.video_id == video_id).first()
        if not video_exists:
            print(f"⚠️ Нельзя сохранить рекомендации: видео {video_id} не найдено в таблице videos")
            return

        existing = session.query(Recommendation).filter(
            Recommendation.video_id == video_id
        ).first()

        if existing:
            existing.data = recommendation
        else:
            session.add(Recommendation(video_id=video_id, data=recommendation))

        session.commit()
        print(f"✅ Рекомендации сохранены в БД: {video_id}")

    except Exception as e:
        session.rollback()
        print(f"🚨 Ошибка сохранения рекомендаций: {e}")
    finally:
        session.close()


def save_audio_to_cache(video_id: str, audio_data: bytes):
    session = SessionLocal()
    try:
        existing = session.query(PodcastAudio).filter(
            PodcastAudio.video_id == video_id
        ).first()

        if existing:
            existing.audio_data = audio_data
        else:
            session.add(PodcastAudio(video_id=video_id, audio_data=audio_data))

        session.commit()
        print(f"✅ Аудио сохранено в БД: {video_id}")

    except Exception as e:
        session.rollback()
        print(f"🚨 Ошибка сохранения аудио: {e}")
    finally:
        session.close()



def delete_cache(video_id: str):
    session = SessionLocal()
    try:
        _delete_children(session, video_id)
        session.query(Video).filter(Video.video_id == video_id).delete()
        session.commit()
        print(f"✅ Кэш удалён: {video_id}")
    except Exception as e:
        session.rollback()
        print(f"🚨 Ошибка удаления: {e}")
    finally:
        session.close()


def delete_expired_cache(days: int = 7):
    session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        old_videos = session.query(Video).filter(Video.created_at < cutoff).all()

        for video in old_videos:
            _delete_children(session, video.video_id)
            session.delete(video)
            print(f"🗑️ Удалён: {video.video_id}")

        session.commit()
        print(f"✅ Очистка завершена — удалено {len(old_videos)} видео")

    except Exception as e:
        session.rollback()
        print(f"🚨 Ошибка очистки: {e}")
    finally:
        session.close()