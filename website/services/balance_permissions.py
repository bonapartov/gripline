"""
Права доступа к данным развесовки (Kart/Setup) — Блок 3 ТЗ «Сервис расчёта
развесовки карта», раздел 4.2. Права — от принадлежности карта/сетапа, а не
от роли пользователя. Единственное место, где живёт эта логика: любой view
в website/balance_setup_views.py и teams/balance_roster_views.py обязан
вызывать эти функции, а не переизобретать видимость/права инлайн.
"""
from functools import reduce
from operator import or_

from django.db.models import Q

from website.models import Kart, Setup, Team


def get_balance_identity(user):
    """
    -> {'driver': Driver|None, 'managed_teams': QuerySet[Team]}

    driver — тот же критерий владения, что уже используется для медиа-кита
    пилота (website/mediakit_views.py::_is_mediakit_owner): подтверждённая
    администратором привязка профиля (UserProfile.verified), не просто
    наличие UserProfile.driver.

    managed_teams — все команды, где пользователь активный TeamManager.
    role (капитан/менеджер/медиа) НЕ фильтруется — ТЗ §4.2: по умолчанию
    все активные TeamManager команды видят все данные команды; гранулярное
    сужение прав закладывается структурой, но без UI в v1.

    Организатор (нет ни Driver, ни управляемых команд) естественно получает
    driver=None и пустой managed_teams — отдельной ветки «запретить
    организатору» не нужно, отсутствие identity уже равно отсутствию прав.
    """
    if not user.is_authenticated:
        return {"driver": None, "managed_teams": Team.objects.none()}

    profile = getattr(user, "profile", None)
    driver = None
    if profile and profile.verified and profile.driver_id:
        driver = profile.driver

    managed_teams = Team.objects.filter(
        managers__user=user, managers__is_active=True,
    ).distinct()
    return {"driver": driver, "managed_teams": managed_teams}


def visible_karts_for_user(user, include_archived=False):
    """Karts, которые пользователь может ВИДЕТЬ (не обязательно править) —
    свои (пилот) плюс все карты команд, которыми он управляет. Флаги шеринга
    живут на Setup, не на Kart — пилот из ростера не получает видимость
    карта команды только из-за привязки; видимость расшаренных ему сетапов
    считается в visible_setups_for_user, здесь не участвует."""
    identity = get_balance_identity(user)
    driver, managed_teams = identity["driver"], identity["managed_teams"]

    conditions = []
    if driver is not None:
        conditions.append(Q(owner_driver=driver))
    if managed_teams.exists():
        conditions.append(Q(owner_team__in=managed_teams))
    if not conditions:
        return Kart.objects.none()

    qs = Kart.objects.filter(reduce(or_, conditions)).distinct()
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return qs


def visible_setups_for_user(user, include_archived=False):
    """Setups, которые пользователь может ВИДЕТЬ — свои (через владение
    картом) плюс расшаренные ему:
    - пилоту: shared_with_driver=True на карте команды, где он закреплён
      в ростере (kart.roster_entry.driver)
    - менеджеру: shared_with_team=True на карте пилота, состоящего (когда-
      либо, не только сейчас — TeamMembership любой, не только is_active)
      в управляемой команде. Намеренно не фильтруем по is_active=True:
      ТЗ §4.6 явно требует, чтобы уход пилота из команды НЕ отзывал
      автоматически доступ команды к уже расшаренным сетапам."""
    identity = get_balance_identity(user)
    driver, managed_teams = identity["driver"], identity["managed_teams"]

    conditions = []
    if driver is not None:
        conditions.append(Q(kart__owner_driver=driver))
        conditions.append(Q(
            kart__owner_team__isnull=False,
            kart__roster_entry__driver=driver,
            shared_with_driver=True,
        ))
    if managed_teams.exists():
        conditions.append(Q(kart__owner_team__in=managed_teams))
        conditions.append(Q(
            kart__owner_driver__team_memberships__team__in=managed_teams,
            shared_with_team=True,
        ))
    if not conditions:
        return Setup.objects.none()

    qs = Setup.objects.filter(reduce(or_, conditions)).distinct()
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return qs


def can_edit_kart(user, kart):
    """Владелец может править. Шеринга на уровне Kart не существует — карт
    либо твой (лично или через управляемую команду), либо нет."""
    identity = get_balance_identity(user)
    driver, managed_teams = identity["driver"], identity["managed_teams"]
    if driver is not None and kart.owner_driver_id == driver.id:
        return True
    if kart.owner_team_id and managed_teams.filter(pk=kart.owner_team_id).exists():
        return True
    return False


def can_edit_setup(user, setup):
    """Право редактировать Setup — целиком транзитивно через владение его
    Kart (у Setup нет собственного поля владельца). Получатель шера
    (shared_with_team/shared_with_driver) видит, но не редактирует и не
    может скопировать — см. план Блока 3, решение 2 (ТЗ §4.3 явно этого не
    оговаривает, это осознанный дефолт, а не факт из ТЗ)."""
    return can_edit_kart(user, setup.kart)
