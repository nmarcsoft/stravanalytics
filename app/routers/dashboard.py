from datetime import datetime, date, timedelta
from typing import Optional
import calendar

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Activity
from ..strava import sync_activities, _refresh_if_needed

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_TYPE_COLORS = {"VMA": "#EF4444", "SEUIL": "#F59E0B", "EF": "#10B981", "OTHER": "#6B7280"}
_TYPE_LABELS = {"VMA": "VMA", "SEUIL": "Seuil", "EF": "EF", "OTHER": "Autre"}
_STYPE_ORDER = ("VMA", "SEUIL", "EF", "OTHER")
_PER_PAGE = 25


def _current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.query(User).filter_by(id=uid).first()


def _fmt_pace(pace: float | None) -> str:
    if pace is None:
        return "-"
    m = int(pace)
    s = int((pace - m) * 60)
    return f"{m}:{s:02d}"


def _apply_filters(query, user_id: int, date_from, date_to, title_contains,
                   description_contains, distance_min, distance_max,
                   elevation_min, elevation_max):
    query = query.filter(Activity.user_id == user_id)
    if date_from:
        query = query.filter(Activity.start_date >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Activity.start_date <= datetime.fromisoformat(date_to))
    if title_contains:
        query = query.filter(Activity.name.ilike(f"%{title_contains}%"))
    if description_contains:
        query = query.filter(Activity.description.ilike(f"%{description_contains}%"))
    if distance_min is not None:
        query = query.filter(Activity.distance >= distance_min * 1000)
    if distance_max is not None:
        query = query.filter(Activity.distance <= distance_max * 1000)
    if elevation_min is not None:
        query = query.filter(Activity.total_elevation_gain >= elevation_min)
    if elevation_max is not None:
        query = query.filter(Activity.total_elevation_gain <= elevation_max)
    return query


def _filter_by_types(query, selected_types: set[str]):
    conditions = []
    for t in selected_types:
        conditions.append(and_(Activity.session_type_override == t))
        conditions.append(and_(Activity.session_type_override.is_(None), Activity.session_type == t))
    return query.filter(or_(*conditions))


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, user: Optional[User] = Depends(_current_user)):
    if not user:
        return templates.TemplateResponse("login.html", {"request": request,
                                                          "error": request.query_params.get("error")})
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "filters": user.last_filters or {},
    })


@router.get("/map", response_class=HTMLResponse)
async def map_page(request: Request, user: Optional[User] = Depends(_current_user)):
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "error": None})
    return templates.TemplateResponse("map.html", {
        "request": request, "user": user, "filters": user.last_filters or {},
    })


@router.get("/duel", response_class=HTMLResponse)
async def duel_page(request: Request, user: Optional[User] = Depends(_current_user)):
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "error": None})
    return templates.TemplateResponse("duel.html", {
        "request": request, "user": user, "filters": user.last_filters or {},
    })


# ── API ────────────────────────────────────────────────────────────────────────

@router.post("/api/sync")
async def api_sync(request: Request, db: Session = Depends(get_db),
                   user: Optional[User] = Depends(_current_user)):
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        count = await sync_activities(user, db)
        return JSONResponse({"synced": count})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/chart-data")
async def api_chart_data(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    title_contains: Optional[str] = None,
    description_contains: Optional[str] = None,
    distance_min: Optional[float] = None,
    distance_max: Optional[float] = None,
    elevation_min: Optional[float] = None,
    elevation_max: Optional[float] = None,
    session_types: Optional[str] = None,
):
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    user.last_filters = {
        "date_from": date_from, "date_to": date_to,
        "title_contains": title_contains, "description_contains": description_contains,
        "distance_min": distance_min, "distance_max": distance_max,
        "elevation_min": elevation_min, "elevation_max": elevation_max,
        "session_types": session_types,
    }
    db.commit()

    selected = set(session_types.split(",")) if session_types else {"VMA", "SEUIL", "EF", "OTHER"}

    query = _apply_filters(
        db.query(Activity), user.id, date_from, date_to, title_contains,
        description_contains, distance_min, distance_max, elevation_min, elevation_max,
    )
    query = _filter_by_types(query, selected)
    activities = query.order_by(Activity.start_date).all()

    count = len(activities)
    seq_ids = list(range(1, count + 1))

    _dark = {
        "paper_bgcolor": "#0F172A",
        "plot_bgcolor": "#1E293B",
        "font": {"color": "#F1F5F9", "family": "Inter, system-ui, sans-serif", "size": 11},
        "margin": {"l": 55, "r": 20, "t": 8, "b": 38},
        "hovermode": "closest",
        "xaxis": {
            "title": "Séance",
            "gridcolor": "#334155",
            "zerolinecolor": "#334155",
            "range": [0.5, count + 0.5] if count else [0, 10],
            "tickformat": "d",
        },
    }
    _yg = {"gridcolor": "#334155", "zerolinecolor": "#334155"}

    def _hr_h(a):
        return f"FC: {int(a.average_heartrate)} bpm" if a.average_heartrate else "FC: —"
    def _pace_h(a):
        return f"Allure: {_fmt_pace(a.pace_min_per_km)} /km"
    def _elev_h(a):
        return f"D+: {int(a.total_elevation_gain or 0)} m"

    def _build(y_getter, hover_getter, line_color, show_legend):
        all_ys = [y_getter(a) for a in activities]
        # Line trace at index 0 (rendered behind markers)
        traces = [{
            "name": "_", "type": "scatter", "mode": "lines",
            "x": seq_ids, "y": all_ys,
            "line": {"color": line_color, "width": 1.5},
            "showlegend": False, "hoverinfo": "skip",
        }]
        # Marker traces at indices 1-4 (one per session type)
        for stype in _STYPE_ORDER:
            color = _TYPE_COLORS[stype]
            label = _TYPE_LABELS[stype]
            if stype not in selected:
                traces.append({
                    "name": label, "type": "scatter", "mode": "markers",
                    "x": [], "y": [], "visible": False,
                    "marker": {"color": color, "size": 8},
                    "showlegend": show_legend, "customdata": [],
                })
                continue
            idxs = [i for i, a in enumerate(activities) if a.effective_session_type == stype]
            gacts = [activities[i] for i in idxs]
            traces.append({
                "name": label, "type": "scatter", "mode": "markers",
                "x": [seq_ids[i] for i in idxs],
                "y": [all_ys[i] for i in idxs],
                "marker": {"color": color, "size": 8, "opacity": 0.9},
                "customdata": [a.strava_id for a in gacts],
                "text": [
                    f"<b>{a.name}</b><br>#{seq_ids[i]} · {a.start_date.strftime('%d/%m/%Y')}<br>{hover_getter(a)}"
                    for a, i in zip(gacts, idxs)
                ],
                "hovertemplate": "%{text}<extra></extra>",
                "showlegend": show_legend,
            })
        return traces

    charts = {
        "hr": {
            "traces": _build(lambda a: a.average_heartrate, _hr_h, "#EF4444", True),
            "layout": {**_dark, "showlegend": True,
                       "legend": {"bgcolor": "rgba(30,41,59,0.85)", "bordercolor": "#334155",
                                  "borderwidth": 1, "x": 0.01, "xanchor": "left",
                                  "y": 0.99, "yanchor": "top"},
                       "yaxis": {**_yg, "title": "FC moy (bpm)"}},
        },
        "pace": {
            "traces": _build(lambda a: a.pace_min_per_km, _pace_h, "#10B981", False),
            "layout": {**_dark, "showlegend": False,
                       "yaxis": {**_yg, "title": "Allure (min/km)",
                                 "autorange": "reversed", "tickformat": ".2f"}},
        },
        "elev": {
            "traces": _build(lambda a: a.total_elevation_gain, _elev_h, "#3B82F6", False),
            "layout": {**_dark, "showlegend": False,
                       "yaxis": {**_yg, "title": "Dénivelé+ (m)"}},
        },
    }

    return JSONResponse({"charts": charts, "count": count})


@router.get("/api/activities")
async def api_activities(
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(_current_user),
    page: int = 1,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    title_contains: Optional[str] = None,
    description_contains: Optional[str] = None,
    distance_min: Optional[float] = None,
    distance_max: Optional[float] = None,
    elevation_min: Optional[float] = None,
    elevation_max: Optional[float] = None,
    session_types: Optional[str] = None,
):
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    selected = set(session_types.split(",")) if session_types else {"VMA", "SEUIL", "EF", "OTHER"}
    query = _apply_filters(
        db.query(Activity), user.id, date_from, date_to, title_contains,
        description_contains, distance_min, distance_max, elevation_min, elevation_max,
    )
    query = _filter_by_types(query, selected)

    total = query.count()
    rows = query.order_by(Activity.start_date.desc()).offset((page - 1) * _PER_PAGE).limit(_PER_PAGE).all()

    return JSONResponse({
        "activities": [{
            "id": a.id,
            "strava_id": a.strava_id,
            "name": a.name,
            "date": a.start_date.strftime("%d/%m/%Y"),
            "session_type": a.effective_session_type,
            "session_type_auto": a.session_type,
            "session_type_override": a.session_type_override,
            "distance_km": round(a.distance_km, 2),
            "duration_min": int(a.duration_min),
            "pace": _fmt_pace(a.pace_min_per_km),
            "elevation": int(a.total_elevation_gain or 0),
            "avg_hr": int(a.average_heartrate) if a.average_heartrate else None,
        } for a in rows],
        "total": total,
        "page": page,
        "pages": max(1, (total + _PER_PAGE - 1) // _PER_PAGE),
    })


@router.post("/api/activities/{activity_id}/type")
async def api_set_type(
    activity_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(_current_user),
):
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    new_type = (body.get("session_type") or "").upper() or None

    if new_type and new_type not in ("VMA", "SEUIL", "EF", "OTHER"):
        return JSONResponse({"error": "Type invalide"}, status_code=400)

    act = db.query(Activity).filter_by(id=activity_id, user_id=user.id).first()
    if not act:
        return JSONResponse({"error": "Introuvable"}, status_code=404)

    act.session_type_override = new_type
    db.commit()
    return JSONResponse({"effective_type": act.effective_session_type})


@router.get("/api/map-data")
async def api_map_data(request: Request, db: Session = Depends(get_db),
                       user: Optional[User] = Depends(_current_user)):
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    f = user.last_filters or {}
    # Apply saved filters (date/distance/elevation/title) — types filtered client-side
    with_poly = _apply_filters(
        db.query(Activity), user.id,
        f.get("date_from"), f.get("date_to"),
        f.get("title_contains"), f.get("description_contains"),
        f.get("distance_min"), f.get("distance_max"),
        f.get("elevation_min"), f.get("elevation_max"),
    ).filter(Activity.summary_polyline.isnot(None)).order_by(Activity.start_date).all()

    without_count = db.query(Activity).filter(
        Activity.user_id == user.id,
        Activity.summary_polyline.is_(None),
    ).count()

    return JSONResponse({
        "activities": [{
            "strava_id": a.strava_id,
            "name": a.name,
            "date": a.start_date.strftime("%d/%m/%Y"),
            "type": a.effective_session_type,
            "distance_km": round(a.distance_km, 2),
            "duration_min": int(a.duration_min),
            "pace": _fmt_pace(a.pace_min_per_km),
            "avg_hr": int(a.average_heartrate) if a.average_heartrate else None,
            "elevation": int(a.total_elevation_gain or 0),
            "polyline": a.summary_polyline,
        } for a in with_poly],
        "without_polyline": without_count,
    })


@router.get("/api/activities/{strava_id}/streams")
async def api_streams(strava_id: int, request: Request, db: Session = Depends(get_db),
                      user: Optional[User] = Depends(_current_user)):
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    act = db.query(Activity).filter_by(strava_id=strava_id, user_id=user.id).first()
    if not act:
        return JSONResponse({"error": "Introuvable"}, status_code=404)

    token = await _refresh_if_needed(user, db)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://www.strava.com/api/v3/activities/{strava_id}/streams",
            headers={"Authorization": f"Bearer {token}"},
            params={"keys": "latlng,heartrate,altitude,distance,velocity_smooth",
                    "key_by_type": "true"},
            timeout=15,
        )
    if resp.status_code != 200:
        return JSONResponse({"error": "Strava error"}, status_code=resp.status_code)

    raw = resp.json()
    return JSONResponse({
        "latlng":    raw.get("latlng", {}).get("data", []),
        "heartrate": raw.get("heartrate", {}).get("data", []),
        "altitude":  raw.get("altitude", {}).get("data", []),
        "distance":  raw.get("distance", {}).get("data", []),
        "velocity":  raw.get("velocity_smooth", {}).get("data", []),
    })


@router.get("/api/duel")
async def api_duel(request: Request, db: Session = Depends(get_db),
                   user: Optional[User] = Depends(_current_user),
                   period: str = "week"):
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    today = date.today()

    if period == "week":
        a_start = today - timedelta(days=today.weekday())
        a_end = today
        b_start = a_start - timedelta(days=7)
        b_end = a_start - timedelta(days=1)
        label_a, label_b = "Cette semaine", "Semaine précédente"
    elif period == "month":
        a_start = today.replace(day=1)
        a_end = today
        if today.month == 1:
            b_start = date(today.year - 1, 12, 1)
            b_end = date(today.year - 1, 12, 31)
        else:
            b_start = date(today.year, today.month - 1, 1)
            b_end = date(today.year, today.month - 1,
                         calendar.monthrange(today.year, today.month - 1)[1])
        label_a, label_b = "Ce mois", "Mois précédent"
    else:
        return JSONResponse({"error": "period must be week or month"}, status_code=400)

    def _stats(start, end):
        f = user.last_filters or {}
        base = db.query(Activity).filter(
            Activity.user_id == user.id,
            Activity.start_date >= datetime(start.year, start.month, start.day, 0, 0, 0),
            Activity.start_date <= datetime(end.year, end.month, end.day, 23, 59, 59),
        )
        # Apply non-date saved filters (elevation, distance, types, keywords)
        if f.get("title_contains"):
            base = base.filter(Activity.name.ilike(f"%{f['title_contains']}%"))
        if f.get("description_contains"):
            base = base.filter(Activity.description.ilike(f"%{f['description_contains']}%"))
        if f.get("distance_min") is not None:
            base = base.filter(Activity.distance >= f["distance_min"] * 1000)
        if f.get("distance_max") is not None:
            base = base.filter(Activity.distance <= f["distance_max"] * 1000)
        if f.get("elevation_min") is not None:
            base = base.filter(Activity.total_elevation_gain >= f["elevation_min"])
        if f.get("elevation_max") is not None:
            base = base.filter(Activity.total_elevation_gain <= f["elevation_max"])
        if f.get("session_types"):
            base = _filter_by_types(base, set(f["session_types"].split(",")))
        acts = base.all()
        total_km = sum(a.distance_km for a in acts)
        total_min = sum(a.duration_min for a in acts)
        total_elev = sum(a.total_elevation_gain or 0 for a in acts)
        hr_vals = [a.average_heartrate for a in acts if a.average_heartrate]
        by_type = {t: 0 for t in ("VMA", "SEUIL", "EF", "OTHER")}
        for a in acts:
            by_type[a.effective_session_type] += 1
        return {
            "count": len(acts),
            "km": round(total_km, 1),
            "min": int(total_min),
            "elevation": int(total_elev),
            "avg_hr": round(sum(hr_vals) / len(hr_vals)) if hr_vals else None,
            "avg_pace": round(total_min / total_km, 2) if total_km > 0 else None,
            "by_type": by_type,
        }

    sa, sb = _stats(a_start, a_end), _stats(b_start, b_end)

    def _win(va, vb, higher=True):
        if va is None or vb is None:
            return None
        if va == vb:
            return "tie"
        return "a" if (va > vb) == higher else "b"

    winners = {
        "km":        _win(sa["km"], sb["km"]),
        "count":     _win(sa["count"], sb["count"]),
        "elevation": _win(sa["elevation"], sb["elevation"]),
        "pace":      _win(sa["avg_pace"], sb["avg_pace"], higher=False),
    }
    score_a = sum(1 for v in winners.values() if v == "a")
    score_b = sum(1 for v in winners.values() if v == "b")

    return JSONResponse({
        "period_a": {"label": label_a, "start": str(a_start), "end": str(a_end), "stats": sa},
        "period_b": {"label": label_b, "start": str(b_start), "end": str(b_end), "stats": sb},
        "winners": winners,
        "score": {"a": score_a, "b": score_b},
    })
