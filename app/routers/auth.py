import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User

router = APIRouter()

_STRAVA_AUTH = "https://www.strava.com/oauth/authorize"
_STRAVA_TOKEN = "https://www.strava.com/oauth/token"
_SCOPES = "activity:read_all"


@router.get("/login")
async def login():
    callback = f"{settings.BASE_URL}/auth/callback"
    url = (
        f"{_STRAVA_AUTH}"
        f"?client_id={settings.STRAVA_CLIENT_ID}"
        f"&redirect_uri={callback}"
        f"&response_type=code"
        f"&scope={_SCOPES}"
        f"&approval_prompt=auto"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str = None,
    error: str = None,
):
    if error or not code:
        return RedirectResponse("/?error=auth_failed")

    async with httpx.AsyncClient() as client:
        resp = await client.post(_STRAVA_TOKEN, data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()

    athlete = data["athlete"]
    user = db.query(User).filter_by(strava_id=athlete["id"]).first()
    if not user:
        user = User(strava_id=athlete["id"])
        db.add(user)

    user.name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    user.profile_url = athlete.get("profile")
    user.access_token = data["access_token"]
    user.refresh_token = data["refresh_token"]
    user.token_expires_at = data["expires_at"]
    db.commit()
    db.refresh(user)

    request.session["user_id"] = user.id
    return RedirectResponse("/")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
