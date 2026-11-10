import logging
import time
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, LargeBinary, Text, UniqueConstraint,
    create_engine, inspect, text,
)
from sqlalchemy.orm import declarative_base, deferred, sessionmaker

import config

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # stored as naive UTC, like the existing rows


def _engine():
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    kwargs = {"pool_pre_ping": True}
    if config.DATABASE_URL.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}  # background jobs use their own threads
    return create_engine(config.DATABASE_URL, **kwargs)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class Video(Base):
    __tablename__ = "videos"
    video_id = Column(Text, primary_key=True)
    title = Column(Text)
    url = Column(Text, nullable=False)
    language = Column(Text)
    duration_sec = Column(Float)
    category = Column(Text)
    created_at = Column(DateTime, default=utcnow, index=True)
    # processing state: rows written before these columns existed were complete, hence the "ready" default
    status = Column(Text, nullable=False, default="processing", server_default="ready")  # processing|ready|rejected|failed
    stage = Column(Text)  # last pipeline stage that started
    error = Column(Text)  # user-facing message of the last failed run
    channel = Column(Text)
    classification = Column(JSON)  # {category, is_suitable, confidence, reason}
    force = Column(Boolean, nullable=False, default=False, server_default=text("false"))  # process despite the classifier
    # youtube | article | text; everything stored before articles existed is a YouTube video
    kind = Column(Text, nullable=False, default="youtube", server_default="youtube")
    # videos: [{start, duration, text}]; articles and pasted text: [{n, section, text}] — kept so steps can be redone
    transcript = deferred(Column(JSON))
    transcript_source = Column(Text)  # manual | generated | whisper | article | pasted
    indexed = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    image_url = Column(Text)  # article cover (og:image)
    word_count = Column(Integer)  # articles and pasted text: for the reading time
    anchors = Column(JSON)  # articles: {"N": first words of paragraph N} for links into the original page
    metrics = Column(JSON)  # how the processing went: seconds per step, time to first words, tokens, model
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Summary(Base):
    __tablename__ = "summaries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Text, ForeignKey("videos.video_id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Keyword(Base):
    __tablename__ = "keywords"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Text, ForeignKey("videos.video_id"), nullable=False, index=True)
    keyword = Column(Text, nullable=False)


class PodcastScript(Base):
    __tablename__ = "podcast_scripts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Text, ForeignKey("videos.video_id"), nullable=False, index=True)
    script = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class PodcastAudio(Base):
    __tablename__ = "podcast_audio"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Text, ForeignKey("videos.video_id"), nullable=False, unique=True)
    audio_data = deferred(Column(LargeBinary, nullable=False))  # loaded only when the file itself is needed
    created_at = Column(DateTime, default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Text, ForeignKey("videos.video_id"), nullable=False, unique=True)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class QAAnswer(Base):
    """Answers to questions asked without chat history (the quiz questions, the suggested ones)."""
    __tablename__ = "qa_answers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Text, ForeignKey("videos.video_id"), nullable=False, index=True)
    question_key = Column(Text, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    sources = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("video_id", "question_key", name="uq_qa_video_question"),)


def migrate(bind=None) -> None:
    """Additive, idempotent schema sync: new tables, new columns and missing indexes on existing tables.

    create_all() alone never touches tables that already exist, so databases created by older versions
    would miss the new columns and the indexes on video_id."""
    bind = bind or engine
    Base.metadata.create_all(bind)
    insp = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            columns = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in columns:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(bind.dialect)}"
                if col.server_default is not None:
                    default = col.server_default.arg
                    default = default.text if hasattr(default, "text") else f"'{default}'"
                    ddl += f" DEFAULT {default}"
                if not col.nullable:
                    ddl += " NOT NULL"
                conn.execute(text(ddl))
                log.info("migrate: added column %s.%s", table.name, col.name)
            indexes = {ix["name"] for ix in insp.get_indexes(table.name)}
            for ix in table.indexes:
                if ix.name not in indexes:
                    ix.create(conn)
                    log.info("migrate: created index %s", ix.name)


def init_db(attempts: int = 30, delay: float = 1.0) -> None:
    """Waits for the database (docker compose starts Postgres and the API together), then migrates."""
    for attempt in range(1, attempts + 1):
        try:
            migrate()
            log.info("БД готова")
            return
        except Exception as e:  # noqa: BLE001 — any connection error means "not ready yet"
            if attempt == attempts:
                raise
            log.warning("БД недоступна (%s), повтор через %.0f с", type(e).__name__, delay)
            time.sleep(delay)

