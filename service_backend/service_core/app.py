from pathlib import Path
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
from .config import CORE_HOST, CORE_PORT, MANUAL_PACKAGE_DIR, CLIENT_OS, CLIENT_ARCH
from .auth import login_ok, issue_token, require_auth
from .db import init_db, list_packages, latest_package, add_package, log_download, stats, set_latest, delete_package, package_exists
import re

VERSION_RE = re.compile(r'^V\d+\.\d+\.\d+$')
from .github_sync import sync_github
from .web_process import start_web

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.get('/api/health')
def health():
    return jsonify({"ok": True, "service": "service_core"})

@app.post('/api/auth/login')
def login():
    body = request.get_json(silent=True) or {}
    if not login_ok(body.get('username'), body.get('password')):
        return jsonify({"error": "invalid credentials"}), 401
    return jsonify({"token": issue_token(), "expiresIn": 3 * 24 * 60 * 60})

@app.get('/api/admin/packages')
@require_auth
def packages():
    return jsonify({"items": list_packages()})

@app.get('/api/admin/stats')
@require_auth
def admin_stats():
    return jsonify(stats())

@app.post('/api/admin/sync')
@require_auth
def sync():
    try:
        return jsonify(sync_github())
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502

@app.post('/api/admin/upload')
@require_auth
def upload():
    file = request.files.get('file')
    version = (request.form.get('version') or '').strip()
    if not file or not file.filename:
        return jsonify({"error": "file is required"}), 400
    name = secure_filename(file.filename)
    if Path(name).suffix.lower() != '.exe':
        return jsonify({"error": "only .exe packages are supported"}), 400
    if not VERSION_RE.fullmatch(version):
        return jsonify({"error": "version must match VX.X.X, for example V1.4.7"}), 400
    if package_exists(version, name, CLIENT_OS, CLIENT_ARCH):
        return jsonify({"error": "this package has already been uploaded", "duplicate": True}), 409
    version_dir = MANUAL_PACKAGE_DIR / version
    version_dir.mkdir(parents=True, exist_ok=True)
    target = version_dir / name
    if target.exists():
        return jsonify({"error": "this package has already been uploaded", "duplicate": True}), 409
    file.save(target)
    package_id = add_package(version, name, 'manual', target, CLIENT_OS, CLIENT_ARCH, request.form.get('release_notes', ''))
    return jsonify({"ok": True, "id": package_id, "filename": name})

@app.delete('/api/admin/packages/<int:package_id>')
@require_auth
def remove_package(package_id):
    package = delete_package(package_id)
    if not package:
        return jsonify({"error": "package not found"}), 404
    try:
        path = Path(package['path'])
        if path.exists(): path.unlink()
        if path.parent.name == package['version'] and not any(path.parent.iterdir()): path.parent.rmdir()
    except OSError:
        pass
    return jsonify({"ok": True})

@app.post('/api/admin/packages/<int:package_id>/latest')
@require_auth
def mark_latest(package_id):
    if not set_latest(package_id):
        return jsonify({"error": "package not found"}), 404
    return jsonify({"ok": True, "id": package_id})

@app.get('/api/client/update/check')
def client_check():
    current = request.args.get('version', '')
    package = latest_package()
    if not package:
        return jsonify({"latest": False, "currentVersion": current})
    return jsonify({"latest": package['version'] == current, "currentVersion": current, "version": package['version'], "source": package['source'], "packageId": package['id'], "filename": package['filename'], "downloadUrl": f"/api/client/update/download/{package['id']}", "releaseNotes": package['release_notes']})

@app.get('/api/client/update/download/<int:package_id>')
def download(package_id):
    from .db import connection
    with connection() as conn:
        row = conn.execute('SELECT * FROM packages WHERE id=?', (package_id,)).fetchone()
    if not row or not Path(row['path']).exists():
        return jsonify({"error": "package not found"}), 404
    log_download(package_id, request.args.get('clientVersion', ''), request.remote_addr or '', True)
    return send_file(row['path'], as_attachment=True, download_name=row['filename'])

def run():
    init_db()
    start_web()
    app.run(host=CORE_HOST, port=CORE_PORT, threaded=True)

if __name__ == '__main__':
    run()
