from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
from models.race import WagtailPage, ArticlePageDB, RaceClassResultGroup, RaceResult, RaceClass
from models.driver import Driver
from auth.jwt import decode_token
from jose import JWTError

router = APIRouter(prefix="/feed", tags=["feed"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

ARTICLE_CT = 1
EVENT_CT = 3


@router.get("")
def get_feed(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """
    Персонализированная лента.
    Для авторизованных пилотов — сначала их последние результаты, потом новости.
    Для остальных — последние результаты и новости.
    """
    user_payload = None
    if token:
        try:
            user_payload = decode_token(token)
        except JWTError:
            pass

    items = []

    # Последние результаты (если авторизован как пилот — его результаты первыми)
    if user_payload and "pilot" in user_payload.get("roles", []) and user_payload.get("driver_id"):
        driver_id = user_payload["driver_id"]
        my_results = (
            db.query(RaceResult, RaceClassResultGroup, WagtailPage, RaceClass, Driver)
            .join(RaceClassResultGroup, RaceResult.group_id == RaceClassResultGroup.id)
            .join(WagtailPage, RaceClassResultGroup.page_id == WagtailPage.id)
            .join(RaceClass, RaceClassResultGroup.race_class_id == RaceClass.id)
            .join(Driver, RaceResult.driver_id == Driver.id)
            .filter(RaceResult.driver_id == driver_id, WagtailPage.live == True)
            .order_by(WagtailPage.first_published_at.desc())
            .limit(5)
            .all()
        )
        for rr, group, page, race_class, driver in my_results:
            items.append({
                "type": "my_result",
                "event_id": page.id,
                "event_title": page.title,
                "date": page.first_published_at,
                "class_name": race_class.name,
                "position": rr.position,
                "points": rr.points,
                "best_lap_ms": rr.best_lap_ms,
                "url": f"https://gripline.ru{page.url_path}",
            })

    # Последние новости
    news_rows = (
        db.query(WagtailPage, ArticlePageDB)
        .join(ArticlePageDB, WagtailPage.id == ArticlePageDB.coderedpage_ptr_id)
        .filter(WagtailPage.live == True, WagtailPage.content_type_id == ARTICLE_CT)
        .order_by(WagtailPage.first_published_at.desc())
        .limit(10)
        .all()
    )
    for page, article in news_rows:
        items.append({
            "type": "news",
            "id": page.id,
            "title": page.title,
            "date": page.first_published_at,
            "caption": article.caption,
            "excerpt": page.search_description,
            "url": f"https://gripline.ru{page.url_path}",
        })

    return items
