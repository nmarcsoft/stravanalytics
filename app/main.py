from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import engine, Base
from .routers.auth import router as auth_router
from .routers.dashboard import router as dashboard_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="StravaAnalytics", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, max_age=86400 * 30)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth_router, prefix="/auth")
app.include_router(dashboard_router)
