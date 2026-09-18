from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.race import RaceClass

router = APIRouter(prefix="/classes", tags=["classes"])

# Порядок отображения классов — синхронизирован вручную с
# website.RaceClass.sort_order (Django — источник правды, эта таблица
# только для чтения, см. CLAUDE.md "FastAPI сервис"). Обновлять оба места
# при добавлении/переименовании классов.
CLASS_ORDER = [
    "Микро", "Мини", "Мини ГР-3", "Супер-мини", "Супер-мини ГР-3",
    "ОК J", "ОК", "KZ2", "KZ2 Masters",
    "RM Micro", "RM Mini", "RM Junior", "RM Senior", "RM DD2", "RM DD2 Masters",
    "4Т Дети", "4Т Юноши", "4Т Взрослые",
    "E-10 БАМБИНИ", "E-10 МИНИ",
]


@router.get("")
def list_classes(db: Session = Depends(get_db)):
    """Список классов картинга."""
    classes = db.query(RaceClass).all()
    classes.sort(key=lambda c: CLASS_ORDER.index(c.name) if c.name in CLASS_ORDER else 99)
    return [{"id": c.id, "name": c.name} for c in classes]
