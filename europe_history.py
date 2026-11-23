"""Durable local posting journal. Keep this SQLite file on persistent storage.

GitHub runners need an explicit durable remote-store adapter before live use.
An unresolved reservation blocks further posting until the operator reconciles
it with Mastodon. Only confirmed successful posts affect country rotation.
"""
import sqlite3
from datetime import datetime, timezone


class PostingHistory:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute('CREATE TABLE IF NOT EXISTS posts (node_id INTEGER PRIMARY KEY, country_code TEXT NOT NULL, state TEXT NOT NULL, status_id TEXT, posted_at TEXT)')
        self.db.commit()

    def successful(self):
        return [dict(node_id=n,country_code=c,status_id=s,posted_at=t) for n,c,s,t in self.db.execute("SELECT node_id,country_code,status_id,posted_at FROM posts WHERE state='posted' ORDER BY posted_at,rowid")]

    def reserve(self, node_id, country_code):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute("SELECT 1 FROM posts WHERE state='pending'").fetchone():
                raise ValueError('Unresolved post: reconcile with Mastodon before retrying')
            if self.db.execute('SELECT 1 FROM posts WHERE node_id=?',(node_id,)).fetchone():
                raise ValueError('Town already posted/reserved')
            previous=self.successful()
            if previous and previous[-1]['country_code']==country_code:
                raise ValueError('Cannot repeat last country')
            self.db.execute("INSERT INTO posts VALUES (?,?,'pending',NULL,NULL)",(node_id,country_code))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def confirm(self, node_id, status_id):
        if not status_id:raise ValueError('Mastodon status ID required')
        with self.db:
            result=self.db.execute("UPDATE posts SET state='posted',status_id=?,posted_at=? WHERE node_id=? AND state='pending'",(str(status_id),datetime.now(timezone.utc).isoformat(),node_id))
            if result.rowcount!=1:raise ValueError('No matching pending reservation')

    def release_confirmed_failure(self, node_id):
        # Use ONLY when it is certain no status was published, never on an
        # ambiguous HTTP timeout after sending a publish request.
        with self.db:
            self.db.execute("DELETE FROM posts WHERE node_id=? AND state='pending'",(node_id,))

    def close(self):
        self.db.close()
