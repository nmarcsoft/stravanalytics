from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Activity
from ..strava import sync_activities

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_TYPE_COLORS = {"VMA": "#EF4444", "SEUIL": "#F59E0B", "EF": "#10B981", "OTHER": "#6B7280"}
_TYPE_LABELS = {"VMA": "VMA", "SEUIL": "Seuil", "EF": "Endurance Fondamentale", "OTHER": "Autre"}
_METRICS = [
    ("pace",         "Allure (min/km)", "y",  True),
    ("distance_km",  "Distance (km)",   "y2", True),
    ("avg_hr",       "FC Moy (bpm)",    "y3", False),
    ("max_hr",       "FC Max (bpm)",    "y4", False),
    ("elevation",    "Dénivelé+ (m)",   "y5", False),
    ("duration_min", "Durée (min)",     "y6", False),
]
_DASH = {"pace": "solid", "distance_km": "dot", "avg_hr": "dash",
         "max_hr": "longdash", "elevation": "dashdot", "duration_min": "longdashdot"}
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
        "request": request,
        "user": user,
        "filters": user.last_filters or {},
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

    # Persister les filtres
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

    traces = []

    for stype in ("VMA", "SEUIL", "EF", "OTHER"):
        if stype not in selected:
            continue
        group = [a for a in activities if a.effective_session_type == stype]
        if not group:
            continue

        color = _TYPE_COLORS[stype]
        label = _TYPE_LABELS[stype]
        dates = [a.start_date.strftime("%Y-%m-%d") for a in group]
        names = [a.name for a in group]

        def _metric_vals(a):
            return {
                "pace":         a.pace_min_per_km,
                "distance_km":  round(a.distance_km, 2),
                "avg_hr":       a.average_heartrate,
                "max_hr":       a.max_heartrate,
                "elevation":    a.total_elevation_gain,
                "duration_min": round(a.duration_min, 1),
            }

        def _hover(a, key):
            mv = _metric_vals(a)
            parts = {
                "pace":         f"Allure: {_fmt_pace(mv['pace'])} min/km",
                "distance_km":  f"Distance: {mv['distance_km']} km",
                "avg_hr":       f"FC moy: {mv['avg_hr']:.0f} bpm" if mv["avg_hr"] else "",
                "max_hr":       f"FC max: {mv['max_hr']:.0f} bpm" if mv["max_hr"] else "",
                "elevation":    f"D+: {mv['elevation']:.0f} m" if mv["elevation"] else "",
                "duration_min": f"Durée: {int(mv['duration_min'])} min",
            }
            return parts[key]

        for metric_key, metric_label, yaxis, default_visible in _METRICS:
            values = [_metric_vals(a)[metric_key] for a in group]
            if not any(v is not None for v in values):
                continue

            hover = [f"<b>{n}</b><br>{_hover(a, metric_key)}" for n, a in zip(names, group)]

            traces.append({
                "name": f"{label} — {metric_label}",
                "type": "scatter",
                "mode": "markers+lines",
                "x": dates,
                "y": values,
                "text": hover,
                "hovertemplate": "%{text}<extra></extra>",
                "marker": {"color": color, "size": 7},
                "line": {"color": color, "dash": _DASH[metric_key], "width": 2},
                "yaxis": yaxis,
                "visible": True if default_visible else "legendonly",
                "legendgroup": f"{stype}_{metric_key}",
            })

    layout = {
        "paper_bgcolor": "#0F172A",
        "plot_bgcolor": "#1E293B",
        "font": {"color": "#F1F5F9", "family": "Inter, system-ui, sans-serif", "size": 12},
        "legend": {
            "bgcolor": "#1E293B", "bordercolor": "#334155", "borderwidth": 1,
            "orientation": "v", "x": 1.02, "xanchor": "left", "y": 1, "yanchor": "top",
            "traceorder": "grouped",
        },
        "margin": {"l": 60, "r": 60, "t": 20, "b": 50},
        "hovermode": "closest",
        "xaxis": {"title": "Date", "gridcolor": "#334155", "zerolinecolor": "#334155"},
        "yaxis":  {"title": "Allure (min/km)", "gridcolor": "#334155", "autorange": "reversed",
                   "tickformat": ".2f", "side": "left"},
        "yaxis2": {"title": "Distance (km)", "overlaying": "y", "side": "right",
                   "showgrid": False, "anchor": "free", "position": 1.0},
        "yaxis3": {"title": "FC Moy (bpm)", "overlaying": "y", "side": "right",
                   "showgrid": False, "anchor": "free", "position": 0.93},
        "yaxis4": {"title": "FC Max (bpm)", "overlaying": "y", "side": "right",
                   "showgrid": False, "anchor": "free", "position": 0.86},
        "yaxis5": {"title": "Dénivelé+ (m)", "overlaying": "y", "side": "right",
                   "showgrid": False, "anchor": "free", "position": 0.79},
        "yaxis6": {"title": "Durée (min)", "overlaying": "y", "side": "right",
                   "showgrid": False, "anchor": "free", "position": 0.72},
    }

    return JSONResponse({"traces": traces, "layout": layout, "count": len(activities)})


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
