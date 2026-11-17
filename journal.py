"""Local bookmarks and a single working trail. Each checkpoint is one transaction."""
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


class Journal:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / "journal.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS bookmarks(url TEXT PRIMARY KEY, title TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints(
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                note TEXT NOT NULL, created TEXT NOT NULL, png BLOB NOT NULL
            );
        """)

    def bookmarks(self):
        return self.db.execute("SELECT url, title FROM bookmarks ORDER BY title, url").fetchall()

    def toggle_bookmark(self, url, title):
        with self.db:
            if self.db.execute("DELETE FROM bookmarks WHERE url=?", (url,)).rowcount:
                return False
            self.db.execute("INSERT INTO bookmarks VALUES(?,?)", (url, title))
            return True

    def capture(self, title, url, note, png):
        with self.db:
            self.db.execute("INSERT INTO checkpoints(title,url,note,created,png) VALUES(?,?,?,?,?)",
                            (title, url, note, datetime.now(timezone.utc).isoformat(timespec="seconds"), png))

    def steps(self):
        return self.db.execute("SELECT id,title,url,note,created FROM checkpoints ORDER BY id").fetchall()

    def remove(self, step_id):
        with self.db:
            self.db.execute("DELETE FROM checkpoints WHERE id=?", (step_id,))

    def export(self, destination):
        destination = Path(destination)
        fd, tmp = tempfile.mkstemp(dir=destination.parent)
        os.close(fd)
        try:
            cards, records = [], []
            with ZipFile(tmp, "w", ZIP_DEFLATED) as out:
                for index, row in enumerate(self.db.execute("SELECT * FROM checkpoints ORDER BY id"), 1):
                    name = f"images/step-{index:03}.png"
                    record = {key: row[key] for key in ("title", "url", "note", "created")}
                    records.append(dict(record, image=name))
                    out.writestr(name, row["png"])
                    fields = {key: escape(value) for key, value in record.items()}
                    cards.append(f"""<article><small>STEP {index:02} · {fields['created']}</small>
                        <h2>{fields['title']}</h2><code>{fields['url']}</code>
                        <p>{fields['note']}</p><img src="{name}" alt="Captured viewport"></article>""")
                out.writestr("trail.json", json.dumps(records, indent=2, ensure_ascii=False))
                out.writestr("index.html", """<!doctype html><html lang="en"><meta charset="utf-8">
                    <meta name="viewport" content="width=device-width,initial-scale=1">
                    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'">
                    <title>Traceleaf trail</title><style>body{background:#f3f5ec;color:#203830;
                    max-width:940px;margin:48px auto;padding:0 20px;font:16px system-ui}
                    article{background:white;border:1px solid #cbd6c5;border-radius:12px;padding:24px;margin:20px 0}
                    img{width:100%;height:auto}small{color:#456355}p{white-space:pre-wrap}
                    h2,p,code{overflow-wrap:anywhere}</style><h1>Traceleaf trail</h1>""" + "".join(cards))
            os.replace(tmp, destination)
        finally:
            Path(tmp).unlink(missing_ok=True)
