import json
import threading
from flask import Flask, Response, abort, send_from_directory
from waitress import create_server
from .config import WEB_DIR, WEB_HOST, WEB_PORT, CORE_PORT

def start_web():
    root = WEB_DIR.resolve()
    if not (root / "index.html").is_file():
        raise RuntimeError("Vue build not found: " + str(root))
    web = Flask("time_tip_web", static_folder=None)
    @web.get("/runtime-config.js")
    def runtime_config():
        return Response("window.TIMETIP_CONFIG=" + json.dumps({"corePort": CORE_PORT}) + ";", mimetype="application/javascript", headers={"Cache-Control": "no-store"})
    @web.get("/")
    @web.get("/<path:name>")
    def static_file(name="index.html"):
        target = (root / name).resolve()
        if root not in target.parents or any(part.startswith(".") for part in name.split("/")):
            abort(404)
        if not target.is_file():
            if "." in name.rsplit("/", 1)[-1]:
                abort(404)
            name = "index.html"
        return send_from_directory(str(root), name)
    server = create_server(web, host=WEB_HOST, port=WEB_PORT, threads=4)
    threading.Thread(target=server.run, daemon=True, name="web-server").start()
    return server
