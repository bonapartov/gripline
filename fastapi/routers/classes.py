from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.race import RaceClass

router = APIRouter(prefix="/classes", tags=["classes"])

# Порядок отображения классов на сайте
CLASS_ORDER = ["Micro", "Mini", "Junior", "Senior", "DD2", "DD2 Masters"]


@router.get("")
def list_classes(db: Session = Depends(get_db)):
    """Список классов картинга."""
    classes = db.query(RaceClass).all()
    classes.sort(key=lambda c: CLASS_ORDER.index(c.name) if c.name in CLASS_ORDER else 99)
    return [{"id": c.id, "name": c.name} for c in classes]
