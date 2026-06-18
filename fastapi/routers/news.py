from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models.race import WagtailPage, ArticlePageDB

router = APIRouter(prefix="/news", tags=["news"])

# Content type IDs статей
ARTICLE_CT = 1


@router.get("")
def list_news(
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """Список новостей и статей, отсортированных по дате публикации."""
    rows = (
        db.query(WagtailPage, ArticlePageDB)
        .join(ArticlePageDB, WagtailPage.id == ArticlePageDB.coderedpage_ptr_id)
        .filter(WagtailPage.live == True, WagtailPage.content_type_id == ARTICLE_CT)
        .order_by(WagtailPage.first_published_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": page.id,
            "title": page.title,
            "slug": page.slug,
            "date": article.date_display or page.first_published_at,
            "caption": article.caption,
            "author": article.author_display,
            "excerpt": page.search_description,
            "url": f"https://gripline.ru{page.url_path}",
        }
        for page, article in rows
    ]


@router.get("/{article_id}")
def get_article(article_id: int, db: Session = Depends(get_db)):
    """Статья по id."""
    page = db.query(WagtailPage).filter(
        WagtailPage.id == article_id,
        WagtailPage.live == True,
        WagtailPage.content_type_id == ARTICLE_CT,
    ).first()
    if not page:
        raise HTTPException(status_code=404, detail="Статья не найдена")

    article = db.query(ArticlePageDB).filter(
        ArticlePageDB.coderedpage_ptr_id == article_id
    ).first()

    return {
        "id": page.id,
        "title": page.title,
        "slug": page.slug,
        "date": article.date_display if article else page.first_published_at,
        "caption": article.caption if article else None,
        "author": article.author_display if article else None,
        "excerpt": page.search_description,
        "url": f"https://gripline.ru{page.url_path}",
    }
