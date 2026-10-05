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
CLAUDE = os.environ.get("CLAUDE_PATH") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")

router = APIRouter()
_pending = {}   # email -> dict(proc, fd, home, t)


def who(request: Request):
    email = (request.headers.get(HEADER) or "").strip().lower() or LAN_USER
    return email or None


def _file(email):
    return DIR / (re.sub(r"[^a-z0-9@._+-]", "_", email) + ".json")


def token_for(email):
    if not email:
        return None
    f = _file(email)
    return json.loads(f.read_text()).get("token") if f.exists() else None


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
    f = _file(email) if email else None
    info = json.loads(f.read_text()) if f and f.exists() else {}
    return dict(enabled=ENABLED, email=email, connected=bool(info.get("token")), connected_at=info.get("connected_at"),
                pending=email in _pending)


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
    DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DIR, 0o700)
    f = _file(email)
    f.write_text(json.dumps(dict(email=email, token=m.group(0), connected_at=time.strftime("%Y-%m-%dT%H:%M:%S"))))
    os.chmod(f, 0o600)
    return dict(ok=True, email=email, connected=True)


@router.post("/api/account/disconnect")
def disconnect(request: Request):
    email = who(request)
    if email:
        _kill(email)
        f = _file(email)
        if f.exists():
            f.unlink()
    return dict(ok=True)
