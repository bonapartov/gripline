from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import and_
from database import get_db
from models.user import AuthUser, UserProfile
from models.driver import Driver
from models.race import RaceClass, RaceClassResultGroup, RaceResult, WagtailPage, TeamMembership, Team
from auth.jwt import decode_token
from jose import JWTError

router = APIRouter(prefix="/pilots", tags=["pilots"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

CHAMPIONSHIP_CT_ID = 4
STAGE_CT_ID = 119
EVENT_CT_ID = 3


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError):
        raise HTTPException(status_code=401, detail="Невалидный токен")
    user = db.query(AuthUser).filter(AuthUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return payload


def _ms_to_str(ms):
    """Конвертирует миллисекунды в строку m:ss.mmm"""
    if ms is None:
        return None
    minutes = ms // 60000
    seconds = (ms % 60000) / 1000
    return f"{minutes}:{seconds:06.3f}"


@router.get("")
def list_pilots(
    class_id: int = Query(None, description="Фильтр по id класса"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """Список пилотов, опционально отфильтрованных по классу, отсортированных по рейтингу."""
    drivers = db.query(Driver).all()

    if class_id:
        # Оставляем только пилотов с рейтингом в этом классе
        result = []
        for d in drivers:
            rb = d.rating_by_class or {}
            if str(class_id) in rb:
                entry = rb[str(class_id)]
                result.append({
                    "id": d.id,
                    "name": f"{d.first_name} {d.last_name}",
                    "slug": d.slug,
                    "city": d.city,
                    "score": entry.get("score"),
                    "starts": entry.get("starts"),
                    "last_race_date": entry.get("last_race_date"),
                })
        result.sort(key=lambda x: x["score"] or 0, reverse=True)
        return result[offset:offset + limit]

    # Без фильтра — все пилоты, у кого есть хоть один класс
    result = []
    for d in drivers:
        rb = d.rating_by_class or {}
        best = max((v.get("score", 0) for v in rb.values()), default=None) if rb else None
        result.append({
            "id": d.id,
            "name": f"{d.first_name} {d.last_name}",
            "slug": d.slug,
            "city": d.city,
            "best_score": best,
        })
    result.sort(key=lambda x: x["best_score"] or 0, reverse=True)
    return result[offset:offset + limit]


@router.get("/{pilot_id}")
def get_pilot(pilot_id: int, db: Session = Depends(get_db)):
    """Профиль пилота."""
    driver = db.query(Driver).filter(Driver.id == pilot_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Пилот не найден")

    # Текущая команда (активная)
    membership = (
        db.query(TeamMembership)
        .filter(TeamMembership.driver_id == pilot_id, TeamMembership.is_active == True)
        .first()
    )
    team_info = None
    if membership:
        team = db.query(Team).filter(Team.id == membership.team_id).first()
        if team:
            team_info = {"id": team.id, "name": team.name, "slug": team.slug}

    return {
        "id": driver.id,
        "name": f"{driver.first_name} {driver.last_name}",
        "first_name": driver.first_name,
        "last_name": driver.last_name,
        "slug": driver.slug,
        "city": driver.city,
        "rating_by_class": driver.rating_by_class,
        "team": team_info,
    }


@router.get("/{pilot_id}/results")
def get_pilot_results(
    pilot_id: int,
    class_id: int = Query(None),
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
):
    """История результатов пилота."""
    driver = db.query(Driver).filter(Driver.id == pilot_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Пилот не найден")

    query = (
        db.query(RaceResult, RaceClassResultGroup, WagtailPage, RaceClass)
        .join(RaceClassResultGroup, RaceResult.group_id == RaceClassResultGroup.id)
        .join(WagtailPage, RaceClassResultGroup.page_id == WagtailPage.id)
        .join(RaceClass, RaceClassResultGroup.race_class_id == RaceClass.id)
        .filter(RaceResult.driver_id == pilot_id, WagtailPage.live == True)
    )
    if class_id:
        query = query.filter(RaceClassResultGroup.race_class_id == class_id)

    rows = query.order_by(WagtailPage.first_published_at.desc()).limit(limit).all()

    results = []
    for rr, group, page, race_class in rows:
        results.append({
            "event_id": page.id,
            "event_title": page.title,
            "event_date": page.first_published_at,
            "class_id": race_class.id,
            "class_name": race_class.name,
            "position": rr.position,
            "start_position": rr.start_position,
            "points": rr.points,
            "race_number": rr.race_number,
            "final": {
                "best_lap": _ms_to_str(rr.best_lap_ms),
                "s1": _ms_to_str(rr.best_s1_ms),
                "s2": _ms_to_str(rr.best_s2_ms),
                "s3": _ms_to_str(rr.best_s3_ms),
            },
            "qualifying": {
                "position": rr.qual_position,
                "best_lap": _ms_to_str(rr.qual_best_lap_ms),
                "s1": _ms_to_str(rr.qual_s1_ms),
                "s2": _ms_to_str(rr.qual_s2_ms),
                "s3": _ms_to_str(rr.qual_s3_ms),
            },
            "pre_final": {
                "position": rr.pre_final_position,
                "start_position": rr.pre_final_start_pos,
                "best_lap": _ms_to_str(rr.pre_final_best_lap_ms),
                "s1": _ms_to_str(rr.pre_final_s1_ms),
                "s2": _ms_to_str(rr.pre_final_s2_ms),
                "s3": _ms_to_str(rr.pre_final_s3_ms),
            },
            "weather": {
                "air_temp": group.air_temperature,
                "humidity": group.humidity,
                "pressure": group.pressure,
                "wind_speed": group.wind_speed,
            },
        })
    return results


@router.get("/{pilot_id}/rating")
def get_pilot_rating(pilot_id: int, db: Session = Depends(get_db)):
    """Рейтинг пилота по классам с именами классов."""
    driver = db.query(Driver).filter(Driver.id == pilot_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Пилот не найден")

    rb = driver.rating_by_class or {}
    if not rb:
        return []

    classes = db.query(RaceClass).filter(RaceClass.id.in_([int(k) for k in rb.keys()])).all()
    class_names = {str(c.id): c.name for c in classes}

    return [
        {
            "class_id": int(class_id),
            "class_name": class_names.get(class_id, ""),
            "score": data.get("score"),
            "starts": data.get("starts"),
            "updated": data.get("updated"),
            "last_race_date": data.get("last_race_date"),
        }
        for class_id, data in sorted(rb.items(), key=lambda x: x[1].get("score", 0), reverse=True)
    ]


# --- Эндпоинты для авторизованного пилота ---

@router.get("/me/profile")
def get_my_profile(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Профиль текущего авторизованного пилота."""
    driver_id = current_user.get("driver_id")
    if not driver_id or "pilot" not in current_user.get("roles", []):
        raise HTTPException(status_code=403, detail="Нет доступа: аккаунт не привязан к пилоту")
    return get_pilot(driver_id, db)
