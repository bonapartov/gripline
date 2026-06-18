from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models.race import (
    WagtailPage, ChampionshipPageDB, StagePageDB, EventPageDB,
    RaceClassResultGroup, RaceResult, RaceClass,
)
from models.driver import Driver

router = APIRouter(tags=["championships"])

# Content type IDs (из Django)
CHAMPIONSHIP_CT = 4
STAGE_CT = 119
EVENT_CT = 3


@router.get("/championships")
def list_championships(db: Session = Depends(get_db)):
    """Список чемпионатов."""
    rows = (
        db.query(WagtailPage, ChampionshipPageDB)
        .join(ChampionshipPageDB, WagtailPage.id == ChampionshipPageDB.coderedpage_ptr_id)
        .filter(WagtailPage.live == True, WagtailPage.content_type_id == CHAMPIONSHIP_CT)
        .order_by(WagtailPage.first_published_at.desc())
        .all()
    )
    return [
        {
            "id": page.id,
            "title": page.title,
            "slug": page.slug,
            "is_completed": champ.is_completed,
            "url": f"https://gripline.ru{page.url_path}",
        }
        for page, champ in rows
    ]


@router.get("/championships/{championship_id}")
def get_championship(championship_id: int, db: Session = Depends(get_db)):
    """Детали чемпионата."""
    page = db.query(WagtailPage).filter(
        WagtailPage.id == championship_id,
        WagtailPage.live == True,
        WagtailPage.content_type_id == CHAMPIONSHIP_CT,
    ).first()
    if not page:
        raise HTTPException(status_code=404, detail="Чемпионат не найден")

    champ = db.query(ChampionshipPageDB).filter(
        ChampionshipPageDB.coderedpage_ptr_id == championship_id
    ).first()

    # Этапы чемпионата (дочерние StagePage)
    stages = _get_stages_for_championship(championship_id, db)

    return {
        "id": page.id,
        "title": page.title,
        "slug": page.slug,
        "is_completed": champ.is_completed if champ else False,
        "description": page.search_description,
        "url": f"https://gripline.ru{page.url_path}",
        "stages": stages,
    }


@router.get("/championships/{championship_id}/stages")
def get_championship_stages(championship_id: int, db: Session = Depends(get_db)):
    """Этапы чемпионата."""
    page = db.query(WagtailPage).filter(
        WagtailPage.id == championship_id,
        WagtailPage.live == True,
    ).first()
    if not page:
        raise HTTPException(status_code=404, detail="Чемпионат не найден")
    return _get_stages_for_championship(championship_id, db)


@router.get("/stages/{stage_id}")
def get_stage(stage_id: int, db: Session = Depends(get_db)):
    """Результаты этапа — все классы и пилоты."""
    page = db.query(WagtailPage).filter(
        WagtailPage.id == stage_id,
        WagtailPage.live == True,
        WagtailPage.content_type_id == STAGE_CT,
    ).first()
    if not page:
        raise HTTPException(status_code=404, detail="Этап не найден")

    stage = db.query(StagePageDB).filter(StagePageDB.coderedpage_ptr_id == stage_id).first()

    # EventPage — дочерние страницы этапа
    events = (
        db.query(WagtailPage)
        .filter(
            WagtailPage.live == True,
            WagtailPage.content_type_id == EVENT_CT,
            WagtailPage.depth == page.depth + 1,
            WagtailPage.path.like(page.path + "%"),
        )
        .all()
    )
    event_ids = [e.id for e in events]

    # Группы результатов для этих событий
    groups = (
        db.query(RaceClassResultGroup, RaceClass)
        .join(RaceClass, RaceClassResultGroup.race_class_id == RaceClass.id)
        .filter(RaceClassResultGroup.page_id.in_(event_ids))
        .all()
    )

    classes_results = []
    for group, race_class in groups:
        results_rows = (
            db.query(RaceResult, Driver)
            .join(Driver, RaceResult.driver_id == Driver.id)
            .filter(RaceResult.group_id == group.id)
            .order_by(RaceResult.position)
            .all()
        )
        classes_results.append({
            "class_id": race_class.id,
            "class_name": race_class.name,
            "weather": {
                "air_temp": group.air_temperature,
                "humidity": group.humidity,
                "pressure": group.pressure,
                "wind_speed": group.wind_speed,
            },
            "results": [
                {
                    "position": rr.position,
                    "driver_id": driver.id,
                    "driver_name": f"{driver.first_name} {driver.last_name}",
                    "driver_slug": driver.slug,
                    "race_number": rr.race_number,
                    "points": rr.points,
                    "start_position": rr.start_position,
                    "best_lap_ms": rr.best_lap_ms,
                }
                for rr, driver in results_rows
            ],
        })

    return {
        "id": page.id,
        "title": page.title,
        "slug": page.slug,
        "start_date": stage.start_date if stage else None,
        "end_date": stage.end_date if stage else None,
        "url": f"https://gripline.ru{page.url_path}",
        "classes": classes_results,
    }


def _get_stages_for_championship(championship_id: int, db: Session):
    """Вспомогательная функция: этапы чемпионата."""
    champ_page = db.query(WagtailPage).filter(WagtailPage.id == championship_id).first()
    if not champ_page:
        return []

    stage_pages = (
        db.query(WagtailPage, StagePageDB)
        .join(StagePageDB, WagtailPage.id == StagePageDB.coderedpage_ptr_id)
        .filter(
            WagtailPage.live == True,
            WagtailPage.content_type_id == STAGE_CT,
            WagtailPage.depth == champ_page.depth + 1,
            WagtailPage.path.like(champ_page.path + "%"),
        )
        .order_by(StagePageDB.start_date)
        .all()
    )

    return [
        {
            "id": page.id,
            "title": page.title,
            "slug": page.slug,
            "start_date": stage.start_date,
            "end_date": stage.end_date,
            "url": f"https://gripline.ru{page.url_path}",
        }
        for page, stage in stage_pages
    ]
