"""Admin panel web application using FastAPI."""
import logging
import bcrypt
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

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
    return RedirectResponse(url="/admin/", status_code=302)


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


@app.get("/logout/")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/", status_code=302)
