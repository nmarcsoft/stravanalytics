import time
import asyncio
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import User, Activity
from .classifier import classify

STRAVA_API = "https://www.strava.com/api/v3"
_CONCURRENT_DETAIL_FETCHES = 5  # limite pour respecter le rate limit Strava


async def _refresh_if_needed(user: User, db: Session) -> str:
    if user.token_expires_at > int(time.time()) + 60:
        return user.access_token

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": settings.STRAVA_CLIENT_ID,
                "client_secret": settings.STRAVA_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": user.refresh_token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

    user.access_token = data["access_token"]
    user.refresh_token = data["refresh_token"]
    user.token_expires_at = data["expires_at"]
    db.commit()
    return user.access_token


async def _fetch_description(client: httpx.AsyncClient, token: str, strava_id: int, sem: asyncio.Semaphore) -> str | None:
    async with sem:
        try:
            resp = await client.get(
                f"{STRAVA_API}/activities/{strava_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("description")
        except Exception:
            pass
    return None


async def sync_activities(user: User, db: Session) -> int:
    token = await _refresh_if_needed(user, db)
    after = int(user.last_sync_at.replace(tzinfo=timezone.utc).timestamp()) if user.last_sync_at else 0

    new_strava_activities: list[dict] = []
    page = 1

    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"{STRAVA_API}/athlete/activities",
                headers={"Authorization": f"Bearer {token}"},
                params={"after": after, "per_page": 200, "page": page},
                timeout=30,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break

            for act in batch:
                if act.get("type") not in ("Run", "VirtualRun", "TrailRun"):
                    continue
                if db.query(Activity).filter_by(strava_id=act["id"]).first():
                    continue
                new_strava_activities.append(act)

            page += 1
            if len(batch) < 200:
                break

        # Récupérer les descriptions en parallèle (limitées par sémaphore)
        sem = asyncio.Semaphore(_CONCURRENT_DETAIL_FETCHES)
        desc_tasks = [
            _fetch_description(client, token, act["id"], sem)
            for act in new_strava_activities
        ]
        descriptions = await asyncio.gather(*desc_tasks)

    for act, description in zip(new_strava_activities, descriptions):
        session_type = classify(act.get("name", ""), description)
        start_date = datetime.fromisoformat(act["start_date"].replace("Z", "+00:00")).replace(tzinfo=None)

        db.add(Activity(
            user_id=user.id,
            strava_id=act["id"],
            name=act.get("name", ""),
            description=description,
            activity_type=act.get("type", "Run"),
            start_date=start_date,
            distance=act.get("distance", 0),
            moving_time=act.get("moving_time", 0),
            total_elevation_gain=act.get("total_elevation_gain", 0),
            average_speed=act.get("average_speed"),
            average_heartrate=act.get("average_heartrate"),
            max_heartrate=act.get("max_heartrate"),
            average_watts=act.get("average_watts"),
            session_type=session_type,
        ))

    user.last_sync_at = datetime.utcnow()
    db.commit()
    return len(new_strava_activities)
