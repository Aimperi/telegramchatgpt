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


@app.get("/video/", response_class=HTMLResponse)
async def video_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/", status_code=302)
    return templates.TemplateResponse("video.html", {"request": request})


@app.get("/video/storage/info")
async def video_storage_info(request: Request):
    """Return R2 bucket usage stats and list of objects."""
    import os
    if not is_authenticated(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")

    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    bucket_name = os.environ.get("CF_R2_BUCKET", "")

    if not all([account_id, bucket_name,
                os.environ.get("CF_R2_ACCESS_KEY_ID"),
                os.environ.get("CF_R2_SECRET_ACCESS_KEY")]):
        return {"error": "R2 not configured. Set CF_ACCOUNT_ID, CF_R2_BUCKET, CF_R2_ACCESS_KEY_ID, CF_R2_SECRET_ACCESS_KEY in Railway."}

    try:
        # List objects via Cloudflare R2 S3-compatible API
        import boto3
        from botocore.config import Config
        endpoint = os.environ.get("CF_R2_ENDPOINT", f"https://{account_id}.r2.cloudflarestorage.com")
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ.get("CF_R2_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.environ.get("CF_R2_SECRET_ACCESS_KEY", ""),
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        resp = s3.list_objects_v2(Bucket=bucket_name, Prefix="video/")
        # Build meta map: slot -> name from meta.json files
        meta_map = {}
        for obj in resp.get("Contents", []):
            if obj["Key"].endswith("/meta.json"):
                try:
                    body = s3.get_object(Bucket=bucket_name, Key=obj["Key"])["Body"].read()
                    import json
                    meta = json.loads(body.decode("utf-8"))
                    m = obj["Key"].split("/")
                    slot_part = next((p for p in m if p.startswith("slot")), None)
                    if slot_part:
                        meta_map[slot_part] = meta.get("name", "")
                except Exception:
                    pass

        objects = []
        total_bytes = 0
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/meta.json"):
                continue  # skip sidecar files
            size = obj["Size"]
            total_bytes += size
            parts = key.split("/")
            slot_part = next((p for p in parts if p.startswith("slot")), None)
            name = meta_map.get(slot_part, parts[-1]) if slot_part else parts[-1]
            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name, "Key": key},
                ExpiresIn=3600,
            )
            objects.append({"key": key, "name": name, "size": size, "url": url})

        return {
            "used_bytes": total_bytes,
            "file_count": len(objects),
            "objects": objects,
        }
    except Exception as e:
        logger.error(f"R2 storage info error: {e}")
        return {"error": str(e)}


@app.post("/video/upload")
async def video_upload(request: Request):
    """Upload video file to R2 into slot{n}/filename."""
    import os
    if not is_authenticated(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")

    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    bucket_name = os.environ.get("CF_R2_BUCKET", "")
    if not all([account_id, bucket_name,
                os.environ.get("CF_R2_ACCESS_KEY_ID"),
                os.environ.get("CF_R2_SECRET_ACCESS_KEY")]):
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="R2 not configured. Set CF_ACCOUNT_ID, CF_R2_BUCKET, CF_R2_ACCESS_KEY_ID, CF_R2_SECRET_ACCESS_KEY in Railway.")

    form = await request.form()
    file = form.get("file")
    slot = form.get("slot", "1")
    name = form.get("name", "").strip() or (file.filename if file else "video")

    if not file:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="No file provided")

    content = await file.read()
    key = f"video/slot{slot}/{file.filename}"
    logger.info(f"R2 upload: slot={slot}, key={key}, size={len(content)}")

    try:
        import boto3, json
        from botocore.config import Config
        endpoint = os.environ.get("CF_R2_ENDPOINT", f"https://{account_id}.r2.cloudflarestorage.com")
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ.get("CF_R2_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.environ.get("CF_R2_SECRET_ACCESS_KEY", ""),
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        # Upload video file (no metadata — S3 metadata is ASCII-only)
        s3.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=content,
            ContentType=file.content_type or "video/mp4",
        )
        # Store name in a sidecar JSON file: video/slot{n}/meta.json
        meta_key = f"video/slot{slot}/meta.json"
        s3.put_object(
            Bucket=bucket_name,
            Key=meta_key,
            Body=json.dumps({"name": name, "file_key": key}, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info(f"R2 upload success: {key}")
        return {"ok": True, "key": key}
    except Exception as e:
        logger.error(f"R2 upload error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


class VideoDeleteRequest(BaseModel):
    key: str


@app.post("/video/delete")
async def video_delete(req: VideoDeleteRequest, request: Request):
    """Delete object from R2 bucket."""
    import os
    if not is_authenticated(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized")

    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    bucket_name = os.environ.get("CF_R2_BUCKET", "")
    if not all([account_id, bucket_name,
                os.environ.get("CF_R2_ACCESS_KEY_ID"),
                os.environ.get("CF_R2_SECRET_ACCESS_KEY")]):
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="R2 not configured")

    try:
        import boto3
        from botocore.config import Config
        endpoint = os.environ.get("CF_R2_ENDPOINT", f"https://{account_id}.r2.cloudflarestorage.com")
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ.get("CF_R2_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.environ.get("CF_R2_SECRET_ACCESS_KEY", ""),
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        s3.delete_object(Bucket=bucket_name, Key=req.key)
        # Also delete sidecar meta.json
        parts = req.key.split("/")
        slot_part = next((p for p in parts if p.startswith("slot")), None)
        if slot_part:
            meta_key = "/".join(parts[:-1]) + "/meta.json"
            try:
                s3.delete_object(Bucket=bucket_name, Key=meta_key)
            except Exception:
                pass
        logger.info(f"R2 delete: {req.key}")
        return {"ok": True}
    except Exception as e:
        logger.error(f"R2 delete error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


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


@app.post("/grok/recognize")
async def grok_recognize(req: GrokRecognizeRequest):
    """Recognize product in image using OpenAI GPT-4o vision (xAI has no vision models in this account)."""
    import os, json
    if not req.image_base64:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="image_base64 is required")

    logger.info(f"Grok recognize: using gpt-4o, image_base64 length={len(req.image_base64)}, prefix='{req.image_base64[:60]}'")

    try:
        from config import BotConfig
        import openai
        cfg = BotConfig.from_env()
        client = openai.AsyncOpenAI(api_key=cfg.openai_api_key)

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
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
                                "Формат:\n"
                                '{"product_name": "название товара (1-5 слов)", '
                                '"seo_description": "SEO описание до 300 символов", '
                                '"description": "описание товара до 300 символов", '
                                '"keywords": ["тег1", "тег2", "тег3", "тег4", "тег5"]}'
                            )
                        }
                    ]
                }
            ],
            max_tokens=600,
            temperature=0.2,
        )

        content = response.choices[0].message.content.strip()
        logger.info(f"GPT-4o recognize raw content: {content[:500]}")

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
        logger.error(f"Recognize JSON parse error: {e}, raw: '{content}'")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Failed to parse AI response: {e}")
    except Exception as e:
        logger.error(f"Recognize error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/openrouter", response_class=HTMLResponse)
async def openrouter_page(request: Request):
    return templates.TemplateResponse("openrouter.html", {"request": request})


@app.get("/openrouter/check")
async def openrouter_check():
    import os
    return {"configured": bool(os.environ.get("OPENROUTER_API_KEY", ""))}


@app.get("/openrouter/models")
async def openrouter_models():
    """Fetch all models from OpenRouter public API."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://openrouter.ai/api/v1/models")
        data = r.json()
        models = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if not mid:
                continue
            pricing = m.get("pricing", {})
            is_free = (
                ":free" in mid or
                (pricing.get("prompt") == "0" and pricing.get("completion") == "0")
            )
            models.append({
                "id": mid,
                "name": m.get("name", mid),
                "free": is_free,
            })
        # Free first, then alphabetical
        models.sort(key=lambda m: (not m["free"], m["id"].lower()))
        return {"models": models}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


class OpenRouterChatRequest(BaseModel):
    model: str
    message: str


@app.post("/openrouter/chat")
async def openrouter_chat(req: OpenRouterChatRequest):
    import os
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY не задан в Railway")
    if not req.message.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="message is required")

    logger.info(f"OpenRouter chat: model={req.model}, msg_len={len(req.message)}")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={"model": req.model, "messages": [{"role": "user", "content": req.message.strip()}]},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://recipebotfather.xyz",
                    "X-Title": "RecipeBotFather",
                },
            )
        logger.info(f"OpenRouter response: {r.status_code}")
        if r.status_code != 200:
            logger.error(f"OpenRouter error: {r.text[:300]}")
            from fastapi import HTTPException
            raise HTTPException(status_code=r.status_code, detail=r.text)
        data = r.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "model": data.get("model", req.model),
            "tokens": data.get("usage", {}).get("total_tokens"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OpenRouter error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/document/", response_class=HTMLResponse)
async def document_page(request: Request):
    return templates.TemplateResponse("document.html", {"request": request})


@app.post("/document/analyze")
async def document_analyze(request: Request):
    """Parse PDF/DOCX, chunk text, analyze via Claude through OpenRouter."""
    import os, json
    from fastapi import HTTPException, UploadFile, File
    from fastapi.datastructures import UploadFile as UploadFileType

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY не задан в Railway")

    form = await request.form()
    file: UploadFileType = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="Файл не загружен")

    content = await file.read()
    filename = file.filename.lower()

    # --- Parse text ---
    text = ""
    try:
        if filename.endswith(".pdf"):
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        elif filename.endswith(".docx"):
            import io
            from docx import Document
            doc = Document(io.BytesIO(content))
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            raise HTTPException(status_code=400, detail="Поддерживаются только PDF и DOCX")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document parse error: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка парсинга файла: {e}")

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Не удалось извлечь текст из документа")

    logger.info(f"Document analyze: file={filename}, text_len={len(text)}")

    # --- Chunk text ~3500 chars ---
    chunk_size = 3500
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    logger.info(f"Document chunks: {len(chunks)}")

    PROMPT_TEMPLATE = """Ты юридический эксперт. Проанализируй следующий фрагмент договора и найди опасные или важные пункты.

Для каждого найденного риска верни JSON объект в массиве "risks":
- level: "high" (высокий риск), "medium" (средний риск), "low" (низкий риск)
- title: краткое название риска (до 10 слов)
- description: пояснение простым языком (до 150 символов)
- quote: цитата из текста (до 200 символов, или null)

Верни ТОЛЬКО валидный JSON без markdown:
{"risks": [...]}

Если рисков нет — верни {"risks": []}

Фрагмент договора:
"""

    all_risks = []

    for i, chunk in enumerate(chunks):
        logger.info(f"Analyzing chunk {i+1}/{len(chunks)}, len={len(chunk)}")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json={
                        "model": "anthropic/claude-sonnet-4-5",
                        "messages": [{"role": "user", "content": PROMPT_TEMPLATE + chunk}],
                        "max_tokens": 1500,
                        "temperature": 0.1,
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://recipebotfather.xyz",
                        "X-Title": "ContractAI",
                    },
                )
            if r.status_code != 200:
                logger.error(f"OpenRouter chunk {i+1} error: {r.status_code} {r.text[:200]}")
                continue

            data = r.json()
            raw = data["choices"][0]["message"]["content"].strip()
            logger.info(f"Chunk {i+1} raw response: {raw[:300]}")

            # Strip markdown fences
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            parsed = json.loads(raw)
            chunk_risks = parsed.get("risks", [])
            all_risks.extend(chunk_risks)
            logger.info(f"Chunk {i+1}: found {len(chunk_risks)} risks")

        except json.JSONDecodeError as e:
            logger.error(f"Chunk {i+1} JSON parse error: {e}, raw: '{raw[:200]}'")
        except Exception as e:
            logger.error(f"Chunk {i+1} error: {e}")

    # --- Generate summary ---
    summary = ""
    high_count = sum(1 for r in all_risks if r.get("level") == "high")
    mid_count = sum(1 for r in all_risks if r.get("level") == "medium")
    low_count = sum(1 for r in all_risks if r.get("level") == "low")

    if all_risks:
        try:
            summary_prompt = (
                f"Договор проанализирован. Найдено рисков: высоких — {high_count}, средних — {mid_count}, низких — {low_count}.\n"
                f"Основные риски:\n" +
                "\n".join(f"- [{r.get('level','?')}] {r.get('title','')}: {r.get('description','')}" for r in all_risks[:10]) +
                "\n\nНапиши краткую итоговую сводку на русском языке (2-3 предложения) для неюриста."
            )
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json={
                        "model": "anthropic/claude-sonnet-4-5",
                        "messages": [{"role": "user", "content": summary_prompt}],
                        "max_tokens": 300,
                        "temperature": 0.3,
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://recipebotfather.xyz",
                        "X-Title": "ContractAI",
                    },
                )
            if r.status_code == 200:
                summary = r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Summary generation error: {e}")
            summary = f"Найдено {len(all_risks)} рисков: {high_count} высоких, {mid_count} средних, {low_count} низких."
    else:
        summary = "Серьёзных рисков не обнаружено. Договор выглядит стандартным."

    return {"risks": all_risks, "summary": summary}


class DocumentReportRequest(BaseModel):
    risks: list
    summary: str = ""


@app.post("/document/report")
async def document_report(req: DocumentReportRequest):
    """Generate PDF report from analysis results."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_LEFT, TA_CENTER

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Normal'], fontSize=18, fontName='Helvetica-Bold', spaceAfter=12, alignment=TA_CENTER)
    heading_style = ParagraphStyle('Heading', parent=styles['Normal'], fontSize=13, fontName='Helvetica-Bold', spaceAfter=6, spaceBefore=12)
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, fontName='Helvetica', spaceAfter=4, leading=14)
    quote_style = ParagraphStyle('Quote', parent=styles['Normal'], fontSize=9, fontName='Helvetica-Oblique', spaceAfter=4, leftIndent=12, textColor=colors.grey)

    LEVEL_COLORS = {
        "high": colors.HexColor("#ef4444"),
        "medium": colors.HexColor("#f59e0b"),
        "low": colors.HexColor("#22c55e"),
    }
    LEVEL_LABELS = {"high": "ВЫСОКИЙ РИСК", "medium": "СРЕДНИЙ РИСК", "low": "НИЗКИЙ РИСК"}

    story = []
    story.append(Paragraph("Анализ договора — Отчёт о рисках", title_style))
    story.append(Spacer(1, 0.3*cm))

    from datetime import datetime
    story.append(Paragraph(f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}", body_style))
    story.append(Spacer(1, 0.4*cm))

    # Summary
    if req.summary:
        story.append(Paragraph("Итоговая сводка", heading_style))
        story.append(Paragraph(req.summary, body_style))
        story.append(Spacer(1, 0.3*cm))

    # Counts
    risks = req.risks
    high = [r for r in risks if r.get("level") == "high"]
    mid = [r for r in risks if r.get("level") == "medium"]
    low = [r for r in risks if r.get("level") == "low"]

    count_data = [
        ["Высокий риск", "Средний риск", "Низкий риск"],
        [str(len(high)), str(len(mid)), str(len(low))],
    ]
    t = Table(count_data, colWidths=[5*cm, 5*cm, 5*cm])
    t.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('FONTNAME', (0,1), (-1,1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,1), (-1,1), 20),
        ('TEXTCOLOR', (0,1), (0,1), LEVEL_COLORS["high"]),
        ('TEXTCOLOR', (1,1), (1,1), LEVEL_COLORS["medium"]),
        ('TEXTCOLOR', (2,1), (2,1), LEVEL_COLORS["low"]),
        ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('ROWBACKGROUNDS', (0,1), (-1,1), [colors.white]),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))

    # Risks by section
    for section_risks, level in [(high, "high"), (mid, "medium"), (low, "low")]:
        if not section_risks:
            continue
        label = LEVEL_LABELS[level]
        color = LEVEL_COLORS[level]
        story.append(Paragraph(f'<font color="#{color.hexval()[2:]}">{label} ({len(section_risks)})</font>', heading_style))
        for r in section_risks:
            title = r.get("title", "")
            desc = r.get("description", "")
            quote = r.get("quote", "")
            story.append(Paragraph(f"<b>{title}</b>", body_style))
            if desc:
                story.append(Paragraph(desc, body_style))
            if quote:
                story.append(Paragraph(f'"{quote}"', quote_style))
            story.append(Spacer(1, 0.15*cm))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=contract-analysis.pdf"}
    )


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


# ── CryptoCloud Payment ──────────────────────────────────────────────────────

import os as _os
CRYPTOCLOUD_API_KEY = _os.environ.get("CRYPTOCLOUD_API_KEY", "")
CRYPTOCLOUD_SHOP_ID = _os.environ.get("CRYPTOCLOUD_SHOP_ID", "")

RECIPE_PRICES = {
    "chicken_rice": {"name": "Курица с рисом", "amount": 5, "currency": "USD"},
    "veggie_stew":  {"name": "Овощное рагу",   "amount": 10, "currency": "USD"},
    "omelette":     {"name": "Омлет с овощами", "amount": 15, "currency": "USD"},
}


class PaymentCreateRequest(BaseModel):
    recipe_id: str
    method: str = "crypto"  # "crypto" or "card"


@app.post("/payment/create")
async def payment_create(req: PaymentCreateRequest):
    """Create CryptoCloud invoice and return payment link."""
    recipe = RECIPE_PRICES.get(req.recipe_id)
    if not recipe:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Unknown recipe_id")

    payload = {
        "amount": recipe["amount"],
        "shop_id": CRYPTOCLOUD_SHOP_ID,
        "currency": recipe["currency"],
        "order_id": req.recipe_id,
        "add_fields": {
            "time_to_pay": {"hours": 1, "minutes": 0}
        }
    }
    # For card payments, request fiat payment method
    if req.method == "card":
        payload["add_fields"]["payment_method"] = "fiat"

    logger.info(f"CryptoCloud create invoice: method={req.method}, {payload}")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.cryptocloud.plus/v2/invoice/create",
                json=payload,
                headers={
                    "Authorization": f"Token {CRYPTOCLOUD_API_KEY}",
                    "Content-Type": "application/json",
                }
            )
        logger.info(f"CryptoCloud response: {r.status_code} {r.text[:300]}")
        if r.status_code != 200:
            from fastapi import HTTPException
            raise HTTPException(status_code=r.status_code, detail=r.text)
        data = r.json()
        link = data["result"]["link"]
        return {"link": link, "recipe": recipe["name"], "amount": recipe["amount"]}
    except Exception as e:
        logger.error(f"CryptoCloud error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(request: Request):
    return templates.TemplateResponse("payment_success.html", {"request": request})


@app.get("/payment/failed", response_class=HTMLResponse)
async def payment_failed(request: Request):
    return templates.TemplateResponse("payment_failed.html", {"request": request})


@app.post("/payment/postback")
async def payment_postback(request: Request):
    """Handle CryptoCloud payment notification."""
    try:
        data = await request.json()
    except Exception:
        data = dict(await request.form())

    status = data.get("status")
    invoice_id = data.get("invoice_id")
    order_id = data.get("order_id")
    currency = data.get("currency")
    amount_crypto = data.get("amount_crypto")

    logger.info(f"CryptoCloud postback: status={status}, invoice_id={invoice_id}, order_id={order_id}, currency={currency}, amount={amount_crypto}")

    if status == "success":
        recipe = RECIPE_PRICES.get(order_id, {})


# ── Lava.top Card Payment ─────────────────────────────────────────────────────

LAVA_API_KEY = _os.environ.get("LAVA_API_KEY", "")
# Single offer ID from lava.top — used for all recipes
LAVA_OFFER_ID = _os.environ.get("LAVA_OFFER_ID", "981cebc8-6e75-4abc-942e-33540b4375b1")


class LavaPaymentRequest(BaseModel):
    recipe_id: str
    email: str


@app.post("/payment/lava/create")
async def lava_payment_create(req: LavaPaymentRequest):
    """Create lava.top invoice for Visa/Mastercard payment."""
    recipe = RECIPE_PRICES.get(req.recipe_id)
    if not recipe:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Unknown recipe_id")

    email = req.email.strip()
    if not email or "@" not in email:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Valid email is required")

    api_key = LAVA_API_KEY
    if not api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="LAVA_API_KEY not configured")

    payload = {
        "email": email,
        "offerId": LAVA_OFFER_ID,
        "currency": "USD",
        "paymentProvider": "UNLIMIT",
        "paymentMethod": "CARD",
        "periodicity": "ONE_TIME",
        "buyerLanguage": "RU",
    }
    logger.info(f"Lava.top create invoice: recipe={req.recipe_id}, email={email}")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://gate.lava.top/api/v3/invoice",
                json=payload,
                headers={
                    "X-Api-Key": api_key,
                    "Content-Type": "application/json",
                }
            )
        logger.info(f"Lava.top response: {r.status_code} {r.text[:300]}")
        if r.status_code not in (200, 201):
            from fastapi import HTTPException
            raise HTTPException(status_code=r.status_code, detail=r.text)
        data = r.json()
        payment_url = data.get("paymentUrl")
        if not payment_url:
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail="No paymentUrl in response")
        return {"link": payment_url, "recipe": recipe["name"], "amount": recipe["amount"]}
    except Exception as e:
        logger.error(f"Lava.top error: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/payment/lava/webhook")
async def lava_webhook(request: Request):
    """Handle lava.top payment webhook (authenticated via X-Api-Key header)."""
    webhook_secret = _os.environ.get("LAVA_WEBHOOK_SECRET", "")
    if webhook_secret:
        incoming_key = request.headers.get("X-Api-Key", "")
        if incoming_key != webhook_secret:
            from fastapi import HTTPException
            logger.warning(f"Lava.top webhook: invalid X-Api-Key")
            raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        data = await request.json()
    except Exception:
        return {"message": "ok"}

    event_type = data.get("eventType")
    status = data.get("status")
    contract_id = data.get("contractId")
    buyer = data.get("buyer", {})
    product = data.get("product", {})

    logger.info(f"Lava.top webhook: event={event_type}, status={status}, contract={contract_id}, buyer={buyer.get('email')}, product={product.get('title')}")

    if event_type == "payment.success":
        logger.info(f"Lava.top payment confirmed: contract={contract_id}")
        # TODO: grant access / send Telegram notification

    return {"message": "ok"}
