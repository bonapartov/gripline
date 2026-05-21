"""
Восстанавливает Wagtail-страницы для чемпионатов и этапов, у которых wagtail_page=None.
Запуск: python manage.py resync_stages
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from wagtail.models import Page


class Command(BaseCommand):
    help = 'Resync missing Wagtail pages for championships and stages'

    def handle(self, *args, **options):
        from organizers.models import Championship, Stage
        from website.models import ChampionshipPage, StagePage, EventPage, EventOccurrence, RaceClassResultGroup, SeasonArchivePage

        # Найти родительскую страницу для чемпионатов
        parent_page = (
            Page.objects.filter(slug='championships').first()
            or SeasonArchivePage.objects.live().first()
            or Page.objects.filter(depth=2).first()
        )
        if not parent_page:
            self.stderr.write('Не найдена родительская страница. Создайте SeasonArchivePage или страницу со slug=championships.')
            return

        self.stdout.write(f'Родительская страница: {parent_page.title} (id={parent_page.id})')
        self.stdout.write(f'Чемпионатов в БД: {Championship.objects.count()}')

        for championship in Championship.objects.prefetch_related('race_classes', 'stages'):
            if not championship.wagtail_page_id:
                slug = championship.slug or slugify(championship.title)
                # Проверяем, нет ли уже такой страницы
                existing = ChampionshipPage.objects.filter(slug=slug).first()
                if existing:
                    championship.wagtail_page = existing
                    championship.save(update_fields=['wagtail_page'])
                    self.stdout.write(f'  Привязан существующий ChampionshipPage для: {championship.title}')
                else:
                    cp = ChampionshipPage(title=championship.title, slug=slug, is_completed=False)
                    parent_page.add_child(instance=cp)
                    cp.save_revision().publish()
                    championship.wagtail_page = cp
                    championship.save(update_fields=['wagtail_page'])
                    self.stdout.write(self.style.SUCCESS(f'  Создан ChampionshipPage для: {championship.title}'))

            classes = list(championship.race_classes.all())
            stages = list(championship.stages.all())
            self.stdout.write(f'  Чемпионат: {championship.title} | wagtail_page={championship.wagtail_page_id} | классов={len(classes)} | этапов={len(stages)}')
            for c in classes:
                self.stdout.write(f'    Класс: {c.name}')

            champ_wagtail = championship.wagtail_page
            if not champ_wagtail:
                self.stderr.write(f'  Пропускаем этапы {championship.title} — нет wagtail_page')
                continue

            champ_page = champ_wagtail.specific

            for stage in championship.stages.all():
                if stage.wagtail_page_id:
                    # Этап есть — создаём EventPage только для недостающих классов
                    sp = stage.wagtail_page.specific
                    existing_class_ids = set(
                        RaceClassResultGroup.objects.filter(
                            page__in=EventPage.objects.child_of(sp)
                        ).values_list('race_class_id', flat=True)
                    )
                    self.stdout.write(f'    Этап: {stage.title} | EventPages={EventPage.objects.child_of(sp).count()} | existing_classes={existing_class_ids}')
                    for race_class in championship.race_classes.all():
                        if race_class.id in existing_class_ids:
                            continue
                        base_slug = slugify(f'{stage.title}-{race_class.name}')
                        slug = base_slug
                        counter = 1
                        while EventPage.objects.filter(slug=slug).exists():
                            slug = f'{base_slug}-{counter}'
                            counter += 1
                        ep = EventPage(
                            title=stage.title,
                            admin_title=f'{stage.title} - {race_class.name}',
                            slug=slug,
                            track=stage.track,
                        )
                        sp.add_child(instance=ep)
                        ep.save_revision().publish()
                        EventOccurrence.objects.create(event=ep, start=stage.start_date, end=stage.end_date)
                        group = RaceClassResultGroup.objects.create(page=ep, race_class=race_class)
                        if championship.default_tyre:
                            group.tyre = championship.default_tyre
                            group.save()
                        self.stdout.write(self.style.SUCCESS(f'      EventPage создан: {race_class.name}'))
                    continue

                sp = StagePage(
                    title=stage.title,
                    start_date=stage.start_date,
                    end_date=stage.end_date,
                    track=stage.track,
                )
                champ_page.add_child(instance=sp)
                sp.save_revision().publish()

                stage.wagtail_page = sp
                stage.save(update_fields=['wagtail_page'])
                self.stdout.write(self.style.SUCCESS(f'    Создан StagePage для: {stage.title}'))

                # EventPage для каждого класса
                for race_class in championship.race_classes.all():
                    base_slug = slugify(f'{stage.title}-{race_class.name}')
                    slug = base_slug
                    counter = 1
                    while EventPage.objects.filter(slug=slug).exists():
                        slug = f'{base_slug}-{counter}'
                        counter += 1

                    ep = EventPage(
                        title=stage.title,
                        admin_title=f'{stage.title} - {race_class.name}',
                        slug=slug,
                        track=stage.track,
                    )
                    sp.add_child(instance=ep)
                    ep.save_revision().publish()

                    EventOccurrence.objects.create(
                        event=ep,
                        start=stage.start_date,
                        end=stage.end_date,
                    )

                    group = RaceClassResultGroup.objects.create(page=ep, race_class=race_class)
                    if championship.default_tyre:
                        group.tyre = championship.default_tyre
                        group.save()

                    self.stdout.write(f'      EventPage: {race_class.name}')

        self.stdout.write(self.style.SUCCESS('Готово.'))
