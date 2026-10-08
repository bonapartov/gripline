"""
Объединяет дубль шасси с основной записью:

    python manage.py merge_chassis --from Cosmik --into Kosmic            # только показать, что будет
    python manage.py merge_chassis --from Cosmik --into Kosmic --apply    # выполнить

Все ссылки на дубль (результаты гонок, карты калькулятора развесовки, соцсети) переносятся на
основную запись, название дубля и его синонимы добавляются в «Синонимы» основной — импорт
протоколов и приложение продолжают находить шасси по старому написанию. Логотип, сайт, страна и
описание дубля переносятся, только если у основной записи их нет. Дубль удаляется.

Всё в одной транзакции. Рейтинги шасси после объединения пересчитать:
    python manage.py update_all_analytics --entity all --model all
и опубликовать справочник приложения (меню «Приложение» → «Публикация»).
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from website.models import Chassis


class Command(BaseCommand):
    help = "Объединить дубль шасси с основной записью (по умолчанию — без изменений, только отчёт)"

    def add_arguments(self, p):
        p.add_argument("--from", dest="source", required=True, help="название дубля (будет удалён)")
        p.add_argument("--into", dest="target", required=True, help="название основной записи")
        p.add_argument("--apply", action="store_true", help="выполнить; без флага — только показать")

    def handle(self, *args, source, target, apply, **o):
        src = Chassis.objects.filter(name__iexact=source.strip()).first()
        dst = Chassis.objects.filter(name__iexact=target.strip()).first()
        if src is None or dst is None:
            raise CommandError(f"Не найдено: {source if src is None else target}")
        if src.pk == dst.pk:
            raise CommandError("Это одна и та же запись")

        relations = [f for f in Chassis._meta.get_fields() if f.one_to_many and f.auto_created]
        counts = {
            f"{f.related_model._meta.verbose_name_plural} ({f.related_model.__name__}.{f.field.name})":
                f.related_model._default_manager.filter(**{f.field.name: src}).count()
            for f in relations
        }
        aliases = []
        for a in [*dst.alias_list(), src.name, *src.alias_list()]:
            if a.casefold() != dst.name.casefold() and a.casefold() not in {x.casefold() for x in aliases}:
                aliases.append(a)
        copied = [name for name in ('logo', 'website', 'country', 'description')
                  if not getattr(dst, name) and getattr(src, name)]

        self.stdout.write(f"{src.name} (id {src.pk}) → {dst.name} (id {dst.pk})")
        for label, n in counts.items():
            self.stdout.write(f"  перенести {label}: {n}")
        self.stdout.write(f"  синонимы {dst.name}: {', '.join(aliases)}")
        if copied:
            self.stdout.write(f"  взять у дубля: {', '.join(copied)}")
        if not apply:
            self.stdout.write(self.style.WARNING("Ничего не изменено. Для выполнения добавьте --apply"))
            return

        with transaction.atomic():
            for f in relations:
                f.related_model._default_manager.filter(**{f.field.name: src}).update(**{f.field.name: dst})
            for name in copied:
                setattr(dst, name, getattr(src, name))
            dst.aliases = ", ".join(aliases)
            dst.save()
            # Сниппет с ревизиями: админка открывает последнюю ревизию — без новой ревизии
            # первое же сохранение в админке вернуло бы старые синонимы.
            dst.save_revision().publish()
            src.delete()
        self.stdout.write(self.style.SUCCESS(f"Готово: {src.name} объединён с {dst.name}"))
