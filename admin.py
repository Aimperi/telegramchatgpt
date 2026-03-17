"""Admin panel web application using FastAPI."""
import logging
import sys
import time
import bcrypt
import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

START_TIME = time.time()
RESTART_COUNT = 0  # incremented on each startup via bot.py if needed

# Health check counters
health_stats = {"total": 0, "success": 0, "failed": 0}

logger = logging.getLogger(__name__)

SECRET_KEY = "f8k2mX9pQr4nL7vZ3wY6tA1sD5hJ0cE"

app = FastAPI(title="Recipe Bot Admin Panel")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Increase max request body size to 20MB for image uploads
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class LargeBodyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request._body_size_limit = 20 * 1024 * 1024  # 20MB
        return await call_next(request)

app.add_middleware(LargeBodyMiddleware)

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


@app.get("/grok/", response_class=HTMLResponse)
async def grok_page(request: Request):
    return templates.TemplateResponse("grok.html", {"request": request})


class GrokGenerateRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "16:9"
    resolution: str = "1k"
    image_base64: str = None


class GrokVideoRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "16:9"
    resolution: str = "480p"
    duration: int = 5
    image_base64: str = None


@app.post("/grok/generate")
async def grok_generate(req: GrokGenerateRequest):
    """Generate image using xAI Grok API."""
    import os
    prompt = req.prompt.strip()
    if not prompt:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Prompt is required")

    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="XAI_API_KEY not configured")

    payload = {
        "model": "grok-imagine-image",
        "prompt": prompt,
        "n": 1,
        "aspect_ratio": req.aspect_ratio,
        "resolution": req.resolution,
        "response_format": "url",
    }
    if req.image_base64:
        payload["image_url"] = req.image_base64
        logger.info(f"Grok image: image_base64 present, length={len(req.image_base64)}, prefix='{req.image_base64[:80]}'")
    else:
        logger.warning("Grok image: NO image_base64 — generating from text only")

    logger.info(f"Grok image generate: prompt='{prompt[:100]}', aspect={req.aspect_ratio}, res={req.resolution}")
    logger.info(f"Grok image payload keys: {list(payload.keys())}")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://api.x.ai/v1/images/generations",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
        logger.info(f"Grok image API status: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"Grok image API error: {response.text}")
            from fastapi import HTTPException
            raise HTTPException(status_code=response.status_code, detail=response.text)
        data = response.json()
        image_url = data["data"][0]["url"]
        return {"image_url": image_url}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Grok image error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/grok/video/start")
async def grok_video_start(req: GrokVideoRequest):
    """Start async video generation using xAI Grok API."""
    import os
    prompt = req.prompt.strip()
    if not prompt:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Prompt is required")

    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="XAI_API_KEY not configured")

    duration = max(1, min(15, req.duration))
    payload = {
        "model": "grok-imagine-video",
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": req.aspect_ratio,
        "resolution": req.resolution,
    }
    if req.image_base64:
        payload["image_url"] = req.image_base64
        img_prefix = req.image_base64[:80]
        img_len = len(req.image_base64)
        logger.info(f"Grok video: image_base64 present, length={img_len}, prefix='{img_prefix}'")
    else:
        logger.warning("Grok video: NO image_base64 provided — will generate from text only!")

    logger.info(f"Grok video start: prompt='{prompt[:100]}', duration={duration}s, aspect={req.aspect_ratio}, res={req.resolution}")
    logger.info(f"Grok video payload keys: {list(payload.keys())}")
    logger.info(f"Grok video image_url in payload: {'image_url' in payload}, payload size approx: {len(str(payload))} chars")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.x.ai/v1/videos/generations",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
        logger.info(f"Grok video start status: {response.status_code}, body: {response.text[:200]}")
        if response.status_code not in (200, 201, 202):
            from fastapi import HTTPException
            raise HTTPException(status_code=response.status_code, detail=response.text)
        data = response.json()
        request_id = data.get("request_id") or data.get("id")
        return {"request_id": request_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Grok video start error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/grok/video/status/{request_id}")
async def grok_video_status(request_id: str):
    """Poll video generation status."""
    import os
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="XAI_API_KEY not configured")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"https://api.x.ai/v1/videos/{request_id}",
                headers={"Authorization": f"Bearer {api_key}"}
            )
        if response.status_code != 200:
            from fastapi import HTTPException
            raise HTTPException(status_code=response.status_code, detail=response.text)
        data = response.json()
        status = data.get("status", "pending")
        if status == "done":
            video = data.get("video", {})
            return {"status": "done", "video_url": video.get("url"), "duration": video.get("duration")}
        return {"status": status}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Grok video status error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


class GrokRecognizeRequest(BaseModel):
    image_base64: str


@app.get("/api/xai/models")
async def get_xai_models():
    """Get list of available xAI models for diagnostics."""
    import os
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="XAI_API_KEY not configured")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.x.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
        logger.info(f"xAI models list status: {r.status_code}, body: {r.text[:1000]}")
        return r.json()
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/grok/recognize")
async def grok_recognize(req: GrokRecognizeRequest):
    """Recognize product in image using xAI Grok vision API."""
    import os, json
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="XAI_API_KEY not configured")
    if not req.image_base64:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="image_base64 is required")

    # No dedicated vision model in account — grok-3 and grok-4 support image input per xAI docs
    vision_models = ["grok-3", "grok-4-0709", "grok-3-mini"]

    # Find first available model that supports images
    working_model = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.x.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
        if r.status_code == 200:
            models_data = r.json()
            available = [m.get("id", "") for m in models_data.get("data", [])]
            logger.info(f"xAI available models: {available}")
            for m in vision_models:
                if m in available:
                    working_model = m
                    break
            logger.info(f"Selected model for vision: {working_model}")
    except Exception as e:
        logger.warning(f"Could not fetch models list: {e}")

    if not working_model:
        working_model = "grok-3"
        logger.warning(f"Falling back to default model: {working_model}")

    payload = {
        "model": working_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": req.image_base64, "detail": "high"}
                    },
                    {
                        "type": "text",
                        "text": (
                            "Распознай товар на изображении и верни ТОЛЬКО валидный JSON без markdown, без пояснений.\n"
                            "Формат ответа:\n"
                            '{"product_name": "название товара (1-5 слов)", '
                            '"seo_description": "SEO описание до 300 символов", '
                            '"description": "описание товара до 300 символов", '
                            '"keywords": ["тег1", "тег2", "тег3", "тег4", "тег5"]}'
                        )
                    }
                ]
            }
        ],
        "max_tokens": 600,
        "temperature": 0.2,
    }

    logger.info(f"Grok recognize: model={working_model}, image_base64 length={len(req.image_base64)}, prefix='{req.image_base64[:60]}'")

    content = ""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.x.ai/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
        logger.info(f"Grok recognize API status: {response.status_code}, body preview: {response.text[:500]}")
        if response.status_code != 200:
            logger.error(f"Grok recognize error body: {response.text}")
            from fastapi import HTTPException
            raise HTTPException(status_code=response.status_code, detail=response.text)

        data = response.json()
        content = data["choices"][0]["message"]["content"].strip()
        logger.info(f"Grok recognize raw content: {content[:500]}")

        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        return {
            "product_name": result.get("product_name", ""),
            "seo_description": result.get("seo_description", ""),
            "description": result.get("description", ""),
            "keywords": result.get("keywords", []),
        }
    except json.JSONDecodeError as e:
        logger.error(f"Grok recognize JSON parse error: {e}, raw content: '{content}'")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Failed to parse AI response: {e}. Raw: {content[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Grok recognize unexpected error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/logout/")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/", status_code=302)


class TTSRequest(BaseModel):
    text: str
    voice: str = "alloy"


ALLOWED_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}

ELEVENLABS_ALLOWED_VOICES = {"dHAwRJVaEPhU907QLTPW", "s0phbFBBp708ZeIy8oGx"}


@app.post("/tts")
async def tts(req: TTSRequest):
    """Generate speech from text using OpenAI TTS API."""
    text = req.text.strip()
    if not text:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Text is required")
    if len(text) > 4096:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Text too long (max 4096 chars)")
    voice = req.voice if req.voice in ALLOWED_VOICES else "alloy"

    try:
        from config import BotConfig
        import openai
        cfg = BotConfig.from_env()
        client = openai.AsyncOpenAI(api_key=cfg.openai_api_key)
        response = await client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
        )
        audio_bytes = response.content
        return StreamingResponse(
            iter([audio_bytes]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"}
        )
    except Exception as e:
        logger.error(f"TTS error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/elevenlabs/voices")
async def get_elevenlabs_voices():
    """Get list of voices from ElevenLabs account."""
    import os
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY not configured")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key}
            )
        data = r.json()
        # Return simplified list: name + voice_id
        voices = [{"name": v.get("name"), "voice_id": v.get("voice_id"), "category": v.get("category")} for v in data.get("voices", [])]
        logger.info(f"ElevenLabs voices in account: {voices}")
        return {"voices": voices}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tts/elevenlabs")
async def tts_elevenlabs(req: TTSRequest):
    """Generate speech using ElevenLabs TTS API."""
    import os
    text = req.text.strip()
    if not text:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Text is required")
    if len(text) > 5000:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Text too long (max 5000 chars)")
    voice_id = req.voice if req.voice in ELEVENLABS_ALLOWED_VOICES else "dHAwRJVaEPhU907QLTPW"

    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY not configured")

    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        logger.info(f"ElevenLabs TTS request: voice_id={voice_id}, text_len={len(text)}, url={url}")
        logger.info(f"ElevenLabs API key present: {bool(api_key)}, key prefix: {api_key[:8]}...")

        async with httpx.AsyncClient(timeout=30) as client:
            # First check what voices are available
            voices_resp = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key}
            )
            voices_data = voices_resp.json()
            available_ids = [v.get("voice_id") for v in voices_data.get("voices", [])]
            logger.info(f"ElevenLabs available voice IDs: {available_ids}")
            logger.info(f"Requested voice_id '{voice_id}' in available: {voice_id in available_ids}")

            response = await client.post(url, json=payload, headers=headers)

        logger.info(f"ElevenLabs response status: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"ElevenLabs error body: {response.text}")
            from fastapi import HTTPException
            raise HTTPException(status_code=response.status_code, detail=response.text)
        return StreamingResponse(
            iter([response.content]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ElevenLabs TTS error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))
