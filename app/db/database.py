from sqlalchemy import create_engine, Column, Text, Float, DateTime, ForeignKey, Integer, LargeBinary
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Video(Base):
    __tablename__ = "videos"
    video_id     = Column(Text, primary_key=True)
    url          = Column(Text, nullable=False)
    language     = Column(Text)
    duration_sec = Column(Float)
    created_at   = Column(DateTime, default=datetime.utcnow)


class Summary(Base):
    __tablename__ = "summaries"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    video_id   = Column(Text, ForeignKey("videos.video_id"), nullable=False)
    content    = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Keyword(Base):
    __tablename__ = "keywords"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Text, ForeignKey("videos.video_id"), nullable=False)
    keyword  = Column(Text, nullable=False)


class PodcastScript(Base):
    __tablename__ = "podcast_scripts"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    video_id   = Column(Text, ForeignKey("videos.video_id"), nullable=False)
    script     = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PodcastAudio(Base):
    __tablename__ = "podcast_audio"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    video_id   = Column(Text, ForeignKey("videos.video_id"), nullable=False, unique=True)
    audio_data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)
    print("✅ БД инициализирована")