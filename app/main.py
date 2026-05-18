from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text, inspect as sa_inspect

from .config import settings
from .database import engine, Base
from .routers.auth import router as auth_router
from .routers.dashboard import router as dashboard_router

Base.metadata.create_all(bind=engine)

# Migrations for columns added after initial deploy
def _migrate():
    insp = sa_inspect(engine)
    if 'activities' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('activities')}
    with engine.connect() as conn:
        if 'summary_polyline' not in cols:
            conn.execute(text("ALTER TABLE activities ADD COLUMN summary_polyline TEXT"))
            conn.commit()

_migrate()

app = FastAPI(title="StravaAnalytics", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, max_age=86400 * 30)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth_router, prefix="/auth")
app.include_router(dashboard_router)
