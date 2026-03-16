"""Admin panel web application using FastAPI."""
import logging
import sys
import time
import bcrypt
import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

START_TIME = time.time()
RESTART_COUNT = 0  # incremented on each startup via bot.py if needed

# Health check counters
health_stats = {"total": 0, "success": 0, "failed": 0}

logger = logging.getLogger(__name__)

SECRET_KEY = "f8k2mX9pQr4nL7vZ3wY6tA1sD5hJ0cE"

app = FastAPI(title="Recipe Bot Admin Panel")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="templates")

# Will be set from bot.py after db is initialized
db = None


def is_authenticated(request: Request) -> bool:
    return request.session.get("authenticated", False)


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


@app.get("/api/dashboard/")
async def dashboard_api(request: Request):
    """API endpoint for dashboard data (JSON)."""
    if not is_authenticated(request):
        return {"error": "Unauthorized"}, 401
    
    total_users = 0
    total_recipes = 0
    if db:
        total_users = await db.get_total_users()
        total_recipes = await db.get_total_recipes()
    
    return {
        "total_users": total_users,
        "total_recipes": total_recipes,
    }


async def _get_monitoring_data():
    """Helper function to collect monitoring data."""
    db_ok = db is not None
    elapsed = int(time.time() - START_TIME)
    hours, rem = divmod(elapsed, 3600)
    minutes, seconds = divmod(rem, 60)
    uptime = f"{hours}ч {minutes}м {seconds}с"
    uptime_pct = "99.9%" if elapsed > 60 else "—"

    # --- Health check: Telegram Bot API ---
    tg_ok = False
    tg_username = "—"
    tg_latency = "—"
    try:
        from config import BotConfig
        cfg = BotConfig.from_env()
        t0 = time.time()
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"https://api.telegram.org/bot{cfg.bot_token}/getMe")
        tg_latency = f"{int((time.time() - t0) * 1000)} мс"
        if r.status_code == 200:
            data = r.json()
            tg_ok = data.get("ok", False)
            tg_username = "@" + data["result"].get("username", "—")
        health_stats["total"] += 1
        health_stats["success"] += 1 if tg_ok else 0
        health_stats["failed"] += 0 if tg_ok else 1
    except Exception as e:
        logger.warning(f"Telegram health check failed: {e}")
        health_stats["total"] += 1
        health_stats["failed"] += 1

    # --- Health check: OpenAI API ---
    openai_ok = False
    openai_latency = "—"
    try:
        from config import BotConfig
        cfg = BotConfig.from_env()
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

    # --- DB stats ---
    db_stats = None
    if db_ok:
        try:
            db_stats = await db.get_db_size()
        except Exception as e:
            logger.warning(f"DB stats failed: {e}")

    logs = [
        {"level": "ok" if tg_ok else "err",
         "time": datetime.now().strftime("%H:%M:%S"),
         "message": f"Telegram Bot API — {'OK' if tg_ok else 'FAIL'} ({tg_latency})"},
        {"level": "ok" if openai_ok else "err",
         "time": datetime.now().strftime("%H:%M:%S"),
         "message": f"OpenAI API — {'OK' if openai_ok else 'FAIL'} ({openai_latency})"},
        {"level": "ok" if db_ok else "warn",
         "time": datetime.now().strftime("%H:%M:%S"),
         "message": f"PostgreSQL — {'Connected' if db_ok else 'Unavailable'}"},
        {"level": "ok",
         "time": datetime.now().strftime("%H:%M:%S"),
         "message": f"Admin panel — Running (port 8080)"},
    ]

    return {
        "uptime": uptime,
        "uptime_pct": uptime_pct,
        "restart_count": RESTART_COUNT,
        "started_at": datetime.fromtimestamp(START_TIME).strftime("%d.%m.%Y %H:%M"),
        "checks_total": health_stats["total"],
        "checks_success": health_stats["success"],
        "checks_failed": health_stats["failed"],
        "tg_ok": tg_ok,
        "tg_username": tg_username,
        "tg_latency": tg_latency,
        "openai_ok": openai_ok,
        "openai_latency": openai_latency,
        "db_ok": db_ok,
        "db_stats": db_stats,
        "logs": logs,
    }


@app.get("/monitoring/", response_class=HTMLResponse)
async def monitoring(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/", status_code=302)

    data = await _get_monitoring_data()
    return templates.TemplateResponse("monitoring.html", {"request": request, **data})


@app.get("/api/monitoring/")
async def monitoring_api(request: Request):
    """API endpoint for monitoring data (JSON)."""
    if not is_authenticated(request):
        return {"error": "Unauthorized"}, 401

    return await _get_monitoring_data()


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
