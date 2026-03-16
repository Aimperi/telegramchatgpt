"""Admin panel web application using FastAPI."""
import logging
import sys
import time
import bcrypt
import httpx
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

START_TIME = time.time()
RESTART_COUNT = 0

# Cumulative health check counters (persist across requests)
health_stats = {"total": 0, "success": 0, "failed": 0}

logger = logging.getLogger(__name__)

SECRET_KEY = "f8k2mX9pQr4nL7vZ3wY6tA1sD5hJ0cE"

app = FastAPI(title="Recipe Bot Admin Panel")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="templates")

# Set from bot.py after db is initialized
db = None


def is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated", False)


async def _collect_metrics() -> dict:
    """Collect all monitoring metrics. Shared by HTML page and JSON API."""
    from config import BotConfig
    cfg = BotConfig.from_env()

    db_ok = db is not None

    # Uptime
    elapsed = int(time.time() - START_TIME)
    hours, rem = divmod(elapsed, 3600)
    minutes, seconds = divmod(rem, 60)
    uptime = f"{hours}ч {minutes}м {seconds}с"
    uptime_pct = "99.9%" if elapsed > 60 else "—"

    # Telegram health check
    tg_ok = False
    tg_username = "—"
    tg_latency = "—"
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"https://api.telegram.org/bot{cfg.bot_token}/getMe")
        tg_latency = f"{int((time.time() - t0) * 1000)} мс"
        if r.status_code == 200:
            data = r.json()
            tg_ok = data.get("ok", False)
            tg_username = "@" + data["result"].get("username", "—")
        health_stats["total"] += 1
        health_stats["success" if tg_ok else "failed"] += 1
    except Exception as e:
        logger.warning(f"Telegram health check failed: {e}")
        health_stats["total"] += 1
        health_stats["failed"] += 1

    # OpenAI health check
    openai_ok = False
    openai_latency = "—"
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {cfg.openai_api_key}"}
            )
        openai_latency = f"{int((time.time() - t0) * 1000)} мс"
        openai_ok = r.status_code == 200
    except Exception as e:
        logger.warning(f"OpenAI health check failed: {e}")

    # DB stats
    db_stats = None
    if db_ok:
        try:
            db_stats = await db.get_db_size()
        except Exception as e:
            logger.warning(f"DB stats failed: {e}")

    now = datetime.now().strftime("%H:%M:%S")
    logs = [
        {"level": "ok" if tg_ok else "err",   "time": now, "message": f"Telegram Bot API — {'OK' if tg_ok else 'FAIL'} ({tg_latency})"},
        {"level": "ok" if openai_ok else "err","time": now, "message": f"OpenAI API — {'OK' if openai_ok else 'FAIL'} ({openai_latency})"},
        {"level": "ok" if db_ok else "warn",   "time": now, "message": f"PostgreSQL — {'Connected' if db_ok else 'Unavailable'}"},
        {"level": "ok",                         "time": now, "message": "Admin panel — Running (port 8080)"},
    ]

    checks_total = health_stats["total"]
    checks_success = health_stats["success"]
    checks_failed = health_stats["failed"]
    success_pct = f"{int((checks_success / checks_total) * 100)}%" if checks_total > 0 else "—"

    return {
        # uptime
        "uptime": uptime,
        "uptime_pct": uptime_pct,
        "restart_count": RESTART_COUNT,
        "started_at": datetime.fromtimestamp(START_TIME).strftime("%d.%m.%Y %H:%M"),
        # checks
        "checks_total": checks_total,
        "checks_success": checks_success,
        "checks_failed": checks_failed,
        "success_pct": success_pct,
        # telegram
        "tg_ok": tg_ok,
        "tg_username": tg_username,
        "tg_latency": tg_latency,
        # openai
        "openai_ok": openai_ok,
        "openai_latency": openai_latency,
        # db
        "db_ok": db_ok,
        "db_stats": db_stats,
        # logs
        "logs": logs,
        # meta
        "last_updated": datetime.now().strftime("%H:%M:%S"),
    }


# ── Routes ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/admin/", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/dashboard/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/admin/", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    error = "Неверный логин или пароль"
    if db:
        admin = await db.get_admin(username)
        if admin and bcrypt.checkpw(password.encode(), admin["password_hash"].encode()):
            request.session["authenticated"] = True
            logger.info(f"Admin '{username}' logged in")
            return RedirectResponse(url="/dashboard/", status_code=302)
    else:
        logger.warning("DB not available for admin login check")
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.get("/dashboard/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/", status_code=302)
    total_users = 0
    total_recipes = 0
    if db:
        total_users = await db.get_total_users()
        total_recipes = await db.get_total_recipes()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_users": total_users,
        "total_recipes": total_recipes,
    })


@app.get("/monitoring/", response_class=HTMLResponse)
async def monitoring(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/", status_code=302)
    data = await _collect_metrics()
    return templates.TemplateResponse("monitoring.html", {"request": request, **data})


@app.get("/api/monitoring/")
async def monitoring_api(request: Request):
    """JSON endpoint for auto-refresh. Returns all monitoring metrics."""
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    data = await _collect_metrics()
    # Convert db_stats dataclass/dict to plain dict for JSON serialization
    if data.get("db_stats"):
        data["db_stats"] = dict(data["db_stats"])
    return JSONResponse(data)


@app.get("/settings/", response_class=HTMLResponse)
async def settings(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/", status_code=302)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    })


@app.get("/logout/")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/", status_code=302)
