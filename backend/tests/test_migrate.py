"""A database created by the previous version keeps its data and gets the new columns and indexes."""
from sqlalchemy import create_engine, inspect, text

from db.database import migrate

OLD_SCHEMA = """
CREATE TABLE videos (video_id TEXT PRIMARY KEY, title TEXT, url TEXT NOT NULL, language TEXT, duration_sec FLOAT,
                     category TEXT, created_at DATETIME);
CREATE TABLE summaries (id INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id), content TEXT NOT NULL,
                        created_at DATETIME);
CREATE TABLE keywords (id INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id), keyword TEXT NOT NULL);
CREATE TABLE podcast_scripts (id INTEGER PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id),
                              script TEXT NOT NULL, created_at DATETIME);
CREATE TABLE podcast_audio (id INTEGER PRIMARY KEY, video_id TEXT NOT NULL UNIQUE REFERENCES videos(video_id),
                            audio_data BLOB NOT NULL, created_at DATETIME);
CREATE TABLE recommendations (id INTEGER PRIMARY KEY, video_id TEXT NOT NULL UNIQUE REFERENCES videos(video_id),
                              data JSON NOT NULL, created_at DATETIME);
INSERT INTO videos VALUES ('OLDOLDOLD01', 'Старое видео', 'https://youtu.be/OLDOLDOLD01', 'ru', 60, 'educational',
                           '2026-01-01 10:00:00');
INSERT INTO summaries (video_id, content) VALUES ('OLDOLDOLD01', '## Обзор');
"""


def test_old_database_is_upgraded_in_place(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        for statement in OLD_SCHEMA.split(";"):
            if statement.strip():
                conn.execute(text(statement))

    migrate(engine)
    migrate(engine)  # idempotent

    insp = inspect(engine)
    columns = {c["name"] for c in insp.get_columns("videos")}
    assert {"status", "stage", "error", "channel", "classification", "force", "transcript", "indexed"} <= columns
    assert "qa_answers" in insp.get_table_names()
    for table in ("summaries", "keywords", "podcast_scripts"):
        assert any(ix["column_names"] == ["video_id"] for ix in insp.get_indexes(table)), table
    with engine.connect() as conn:
        row = conn.execute(text("SELECT status, title, indexed FROM videos")).one()
    assert tuple(row) == ("ready", "Старое видео", 0)  # existing videos count as fully processed
