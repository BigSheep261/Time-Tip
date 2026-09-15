import base64, hashlib, hmac, json, secrets, time
from functools import wraps
from flask import request, jsonify
from .config import AUTH_USERNAME, AUTH_PASSWORD, TOKEN_SECRET, TOKEN_TTL_SECONDS
def _b64(v): return base64.urlsafe_b64encode(v).decode().rstrip('=')
def _unb64(v): return base64.urlsafe_b64decode(v + '=' * (-len(v) % 4))
def issue_token():
    payload = {"jti": secrets.token_urlsafe(24), "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64(json.dumps(payload, separators=(',', ':')).encode()); sig = hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"
def valid_token(token):
    try:
        body, signature = token.split('.', 1); expected = hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).digest()
        return hmac.compare_digest(_unb64(signature), expected) and int(json.loads(_unb64(body))["exp"]) > int(time.time())
    except Exception: return False
def login_ok(username, password): return hmac.compare_digest(username or '', AUTH_USERNAME) and hmac.compare_digest(password or '', AUTH_PASSWORD)
def require_auth(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        if not valid_token(request.headers.get('X-Auth-Token', '')): return jsonify({"error": "unauthorized"}), 401
        return handler(*args, **kwargs)
    return wrapped
