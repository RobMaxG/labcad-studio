"""Per-user Claude accounts, so each person's "Send to Claude" runs on their own subscription.

Off unless LABCAD_ACCOUNTS=1 (then every run needs the asker's own account); with it off, Claude runs on whatever
account the `claude` CLI on this machine is logged in to, exactly as before.

Who's asking comes from an authenticating proxy in front of the Studio, e.g. Cloudflare Access (Cf-Access-Authenticated-User-Email). Each user connects once:
the Studio runs `claude setup-token` in a pseudo-terminal, hands the sign-in URL to the browser, takes the code
the user pastes back, and keeps the resulting long-lived token (one file per user, mode 600). Claude runs then
get it as CLAUDE_CODE_OAUTH_TOKEN. Without a connected account there is no fallback to anyone else's.
"""
import asyncio, fcntl, json, os, re, select, shutil, signal, struct, subprocess, tempfile, termios, time
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

DIR = Path(os.environ.get("LABCAD_ACCOUNTS_DIR") or Path.home() / ".labcad-accounts")
ENABLED = os.environ.get("LABCAD_ACCOUNTS", "").strip().lower() in ("1", "true", "yes", "on")
HEADER = os.environ.get("LABCAD_USER_HEADER", "cf-access-authenticated-user-email").lower()   # set by the proxy, never by the browser
LAN_USER = os.environ.get("LABCAD_LAN_USER", "").strip().lower()   # optional: who direct (non-Cloudflare) visits act as
ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b[=>()][0-9A-Za-z]?")
URL = re.compile(r"https://claude\.(?:com|ai)/\S*oauth/authorize\?[^\s\x07\x1b]+")
TOKEN = re.compile(r"sk-ant-oat[0-9]{2}-[A-Za-z0-9_\-]{20,}")
PENDING_TTL = 900
MODELS = ["opus", "sonnet", "fable"]                       # `claude --model` aliases (always the latest of each)
EFFORTS = ["low", "medium", "high", "xhigh", "max"]       # `claude --effort`; unset = Claude Code's default
DEFAULTS = dict(model="opus", effort="")
CLAUDE = os.environ.get("CLAUDE_PATH") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")

router = APIRouter()
_pending = {}   # email -> dict(proc, fd, home, t)


def who(request: Request):
    email = (request.headers.get(HEADER) or "").strip().lower() or LAN_USER
    return email or None


def _file(email):
    return DIR / (re.sub(r"[^a-z0-9@._+-]", "_", email) + ".json")


def _load(key):
    f = _file(key)
    return json.loads(f.read_text()) if f.exists() else {}


def _save(key, rec):
    DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DIR, 0o700)
    f = _file(key)
    f.write_text(json.dumps(rec))
    os.chmod(f, 0o600)


def token_for(email):
    return _load(email).get("token") if email else None


def _prefs_key(request):
    return who(request) if ENABLED else "_shared"   # accounts off: one shared set of preferences


def prefs(request):
    key = _prefs_key(request)
    rec = _load(key) if key else {}
    return {k: rec.get(k, v) for k, v in DEFAULTS.items()}


def clean(model, effort):
    """Validate a model/effort pair; '' or None means "not set"."""
    if model and model not in MODELS:
        raise HTTPException(400, f"Unknown model {model!r}.")
    if effort and effort not in EFFORTS:
        raise HTTPException(400, f"Unknown effort {effort!r}.")
    return model or None, effort or None


def run_settings(request, model=None, effort=None):
    """(model, effort) for a Claude run: a per-message override wins, then the user's saved choice.
    effort="default" is an explicit "don't pass --effort" (so a message can drop back from a saved level)."""
    explicit_default = effort == "default"
    model, effort = clean(model, None if explicit_default else effort)
    p = prefs(request)
    return model or p["model"] or DEFAULTS["model"], None if explicit_default else (effort or p["effort"] or None)


def need_token(request: Request):
    """(email, token) for a Claude run, or an HTTPException telling the user what to do. (None, None) when accounts are off."""
    if not ENABLED:
        return None, None
    email = who(request)
    if not email:
        raise HTTPException(403, "Open the Studio through its signed-in address to use Claude.")
    tok = token_for(email)
    if not tok:
        raise HTTPException(403, "Connect your Claude account first: Account (top bar) → Connect Claude.")
    return email, tok


def _kill(email):
    p = _pending.pop(email, None)
    if not p:
        return
    try:
        os.killpg(p["proc"].pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    os.close(p["fd"])
    shutil.rmtree(p["home"], ignore_errors=True)


def _read_until(fd, pattern, timeout, buf=""):
    """Read the pty until `pattern` matches the ANSI-stripped text (or timeout / EOF). Returns (match, text)."""
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                chunk = os.read(fd, 65536).decode(errors="replace")
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
        m = pattern.search(ANSI.sub("", buf))
        if m:
            return m, buf
    return None, buf


@router.get("/api/account")
def account(request: Request):
    email = who(request)
    info = _load(email) if email else {}
    return dict(enabled=ENABLED, email=email, connected=bool(info.get("token")), connected_at=info.get("connected_at"),
                pending=email in _pending, prefs=prefs(request), models=MODELS, efforts=EFFORTS)


class PrefsReq(BaseModel):
    model: str = ""
    effort: str = ""


@router.put("/api/account/prefs")
def set_prefs(request: Request, req: PrefsReq):
    key = _prefs_key(request)
    if not key:
        raise HTTPException(403, "Open the Studio through its signed-in address to save settings.")
    model, effort = clean(req.model, req.effort)
    rec = _load(key)
    rec.update(model=model or DEFAULTS["model"], effort=effort or "")
    _save(key, rec)
    return prefs(request)


@router.post("/api/account/login/start")
async def login_start(request: Request):
    email = who(request)
    if not ENABLED:
        raise HTTPException(404, "Per-user Claude accounts are off (LABCAD_ACCOUNTS).")
    if not email:
        raise HTTPException(403, "Open the Studio through its signed-in address to connect Claude.")
    for e in [e for e, p in _pending.items() if time.time() - p["t"] > PENDING_TTL]:
        _kill(e)
    _kill(email)
    home = tempfile.mkdtemp(prefix="labcad-login-")
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 1000, 0, 0))   # wide, so the URL never wraps
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
    env.update(HOME=home, TERM="xterm-256color", BROWSER="/bin/true", COLUMNS="1000", LINES="50")
    proc = subprocess.Popen([CLAUDE, "setup-token"], stdin=slave, stdout=slave, stderr=slave, env=env, cwd=home,
                            start_new_session=True, close_fds=True)
    os.close(slave)
    _pending[email] = dict(proc=proc, fd=master, home=home, t=time.time())
    m, _ = await asyncio.to_thread(_read_until, master, URL, 30)
    if not m:
        _kill(email)
        raise HTTPException(502, "Claude didn't produce a sign-in link. Try again in a minute.")
    return dict(url=m.group(0))


class FinishReq(BaseModel):
    code: str


@router.post("/api/account/login/finish")
async def login_finish(request: Request, req: FinishReq):
    email = who(request)
    p = _pending.get(email or "")
    if not p:
        raise HTTPException(400, "That sign-in expired. Press Connect Claude again.")
    code = req.code.strip()
    if not code:
        raise HTTPException(400, "Paste the code Claude showed you after signing in.")
    for ch in code:   # type it like a person; a single large write can arrive as one keypress-burst Ink drops
        os.write(p["fd"], ch.encode())
    await asyncio.sleep(0.3)
    os.write(p["fd"], b"\r")
    m, buf = await asyncio.to_thread(_read_until, p["fd"], TOKEN, 60)
    _kill(email)
    if not m:
        tail = ANSI.sub("", buf).strip().splitlines()[-3:]
        raise HTTPException(400, "Claude didn't accept that code. " + " ".join(t.strip() for t in tail)[-300:])
    rec = _load(email)
    rec.update(email=email, token=m.group(0), connected_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    _save(email, rec)
    return dict(ok=True, email=email, connected=True)


@router.post("/api/account/disconnect")
def disconnect(request: Request):
    email = who(request)
    if email:
        _kill(email)
        rec = _load(email)
        if rec.pop("token", None) is not None:   # keep their model/effort choice
            rec.pop("connected_at", None)
            _save(email, rec)
    return dict(ok=True)
