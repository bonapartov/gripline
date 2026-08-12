"""
Выбор тегов для анонс-постинга в соцсети — общий для всех каналов
(Telegram, MAX и др.), ничего не знает о конкретном API соцсети.
"""
from django.db.models import Q

from .models import SocialTag


def get_category_tag_for_page(page):
    """Тег, чей parent_page совпадает с фактическим родителем статьи — его
    эмодзи используется как баннер перед заголовком поста. Если таких
    тегов несколько — берём первый по алфавиту (детерминированно)."""
    parent = page.get_parent()
    return SocialTag.objects.filter(parent_page_id=parent.id).order_by('tag').first()


def get_auto_tags_for_page(page):
    """Теги без родительской страницы (публикуются на всех постах) + теги,
    у которых parent_page совпадает с фактическим родителем этой статьи."""
    parent = page.get_parent()
    return list(
        SocialTag.objects.filter(Q(parent_page__isnull=True) | Q(parent_page_id=parent.id)).order_by('tag')
    )


def get_active_tags_for_page(page):
    """Все теги поста: автоматические (по родительской странице/без неё) +
    вручную добавленные на самой статье, без дублей. Публикуются все сразу."""
    auto_tags = get_auto_tags_for_page(page)
    auto_ids = {t.pk for t in auto_tags}
    manual_tags = [t for t in page.social_extra_tags.all() if t.pk not in auto_ids]
    return auto_tags + manual_tags
