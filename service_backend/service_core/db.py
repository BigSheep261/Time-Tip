import sqlite3
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS packages (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL, filename TEXT NOT NULL, source TEXT NOT NULL, path TEXT NOT NULL, os TEXT NOT NULL DEFAULT 'windows', arch TEXT NOT NULL DEFAULT 'x64', release_notes TEXT DEFAULT '', created_at TEXT NOT NULL, is_latest INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS download_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, package_id INTEGER, client_version TEXT, client_ip TEXT, success INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, FOREIGN KEY(package_id) REFERENCES packages(id));
"""
def utc_now(): return datetime.now(timezone.utc).isoformat()
@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    try:
        yield conn; conn.commit()
    finally: conn.close()
def init_db():
    with connection() as conn: conn.executescript(SCHEMA)
def list_packages(limit=100):
    with connection() as conn: return [dict(r) for r in conn.execute("SELECT * FROM packages ORDER BY created_at DESC LIMIT ?", (limit,))]
def latest_package():
    with connection() as conn:
        row = conn.execute("SELECT * FROM packages WHERE is_latest=1 ORDER BY created_at DESC LIMIT 1").fetchone()
        if row: return dict(row)
        rows = conn.execute("SELECT * FROM packages").fetchall()
        def key(r):
            m = re.fullmatch(r'V(\d+)\.(\d+)\.(\d+)', r['version'] or '')
            return tuple(int(x) for x in m.groups()) if m else (-1, -1, -1)
        return dict(max(rows, key=key)) if rows else None
def set_latest(package_id):
    with connection() as conn:
        row = conn.execute("SELECT os, arch FROM packages WHERE id=?", (package_id,)).fetchone()
        if not row: return False
        conn.execute("UPDATE packages SET is_latest=0 WHERE os=? AND arch=?", (row['os'], row['arch']))
        conn.execute("UPDATE packages SET is_latest=1 WHERE id=?", (package_id,))
        return True
def get_package(package_id):
    with connection() as conn:
        row = conn.execute("SELECT * FROM packages WHERE id=?", (package_id,)).fetchone()
        return dict(row) if row else None
def delete_package(package_id):
    with connection() as conn:
        row = conn.execute("SELECT * FROM packages WHERE id=?", (package_id,)).fetchone()
        if not row: return None
        conn.execute("DELETE FROM packages WHERE id=?", (package_id,))
        if row['is_latest']:
            remaining = conn.execute("SELECT id, version FROM packages WHERE os=? AND arch=?", (row['os'], row['arch'])).fetchall()
            if remaining:
                def key(r):
                    m = re.fullmatch(r'V(\d+)\.(\d+)\.(\d+)', r['version'] or '')
                    return tuple(int(x) for x in m.groups()) if m else (-1, -1, -1)
                conn.execute("UPDATE packages SET is_latest=1 WHERE id=?", (max(remaining, key=key)['id'],))
        return dict(row)
def package_exists(version, filename, os_name='windows', arch='x64'):
    with connection() as conn:
        return conn.execute("SELECT id FROM packages WHERE version=? AND filename=? AND os=? AND arch=?", (version, filename, os_name, arch)).fetchone() is not None
def add_package(version, filename, source, path, os_name='windows', arch='x64', notes=''):
    with connection() as conn:
        current = conn.execute("SELECT version FROM packages WHERE os=? AND arch=? AND is_latest=1 LIMIT 1", (os_name, arch)).fetchone()
        def key(v):
            m = re.fullmatch(r'V(\d+)\.(\d+)\.(\d+)', v or '')
            return tuple(int(x) for x in m.groups()) if m else (-1, -1, -1)
        make_latest = current is None or key(version) > key(current['version'])
        if make_latest:
            conn.execute("UPDATE packages SET is_latest=0 WHERE os=? AND arch=?", (os_name, arch))
        cur = conn.execute("INSERT INTO packages(version,filename,source,path,os,arch,release_notes,created_at,is_latest) VALUES(?,?,?,?,?,?,?,?,?)", (version, filename, source, str(path), os_name, arch, notes, utc_now(), int(make_latest)))
        return cur.lastrowid
def log_download(package_id, client_version, client_ip, success=True):
    with connection() as conn: conn.execute("INSERT INTO download_logs(package_id,client_version,client_ip,success,created_at) VALUES(?,?,?,?,?)", (package_id, client_version, client_ip, int(success), utc_now()))
def stats():
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM download_logs").fetchone()["n"]
        success = conn.execute("SELECT COUNT(*) n FROM download_logs WHERE success=1").fetchone()["n"]
        by_source = [dict(r) for r in conn.execute("SELECT p.source, COUNT(l.id) downloads FROM packages p LEFT JOIN download_logs l ON l.package_id=p.id GROUP BY p.source")]
        recent = [dict(r) for r in conn.execute("SELECT l.*, p.version, p.filename, p.source FROM download_logs l LEFT JOIN packages p ON p.id=l.package_id ORDER BY l.created_at DESC LIMIT 50")]
        return {"total_downloads": total, "successful_downloads": success, "by_source": by_source, "recent": recent}
