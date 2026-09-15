import re
from pathlib import Path
import requests
from .config import GITHUB_REPO, GITHUB_BRANCH, GITHUB_TOKEN, GITHUB_PACKAGE_DIR, PACKAGE_EXTENSIONS, CLIENT_OS, CLIENT_ARCH
from .db import add_package
def _version(name):
    m = re.search(r'[vV]?(\d+\.\d+(?:\.\d+){0,2})', name); return m.group(1) if m else 'unknown'
def sync_github():
    if not GITHUB_REPO: return {"ok": False, "message": "GITHUB_REPO is not configured", "count": 0}
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN: headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    response = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/git/trees/{GITHUB_BRANCH}?recursive=1", headers=headers, timeout=30); response.raise_for_status()
    entries = response.json().get('tree', [])
    candidates = [e for e in entries if e.get('type') == 'blob' and Path(e.get('path','')).suffix.lower() in PACKAGE_EXTENSIONS and CLIENT_ARCH in e.get('path','').lower()]
    if not candidates: return {"ok": True, "message": "No matching package found", "count": 0}
    saved = []
    for entry in candidates:
        name = Path(entry['path']).name; target = GITHUB_PACKAGE_DIR / name
        raw = requests.get(f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{entry['path']}", headers=headers, timeout=120); raw.raise_for_status(); target.write_bytes(raw.content)
        add_package(_version(name), name, 'github', target, CLIENT_OS, CLIENT_ARCH); saved.append(name)
    return {"ok": True, "message": "GitHub sync completed", "count": len(saved), "files": saved}
