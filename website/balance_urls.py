from django.urls import path
from . import balance_setup_views, balance_views

app_name = "balance"

urlpatterns = [
    path("", balance_views.balance_home, name="home"),
    path("manifest.json", balance_views.balance_manifest, name="manifest"),
    path("sw.js", balance_views.balance_service_worker, name="service_worker"),

    # Блок 3 (сохранение/шеринг) — см. /home/v/.claude/plans/smooth-snacking-spindle.md.
    # Этап 1: пилотский Kart CRUD. Этап 2: сохранение сетапа (создание).
    # Этап 3: список сохранённых сетапов. Этап 4: загрузка на редактирование + update.
    # Этап 5: копирование. Этап 6: архив/шеринг сетапа.
    path("kart/create/", balance_setup_views.kart_create, name="kart_create"),
    path("kart/<int:pk>/archive/", balance_setup_views.kart_archive, name="kart_archive"),
    path("setup/save/", balance_setup_views.setup_save, name="setup_save"),
    path("setup/<int:pk>/", balance_setup_views.setup_edit, name="setup_edit"),
    path("setup/<int:pk>/copy/", balance_setup_views.setup_copy, name="setup_copy"),
    path("setup/<int:pk>/archive/", balance_setup_views.setup_archive, name="setup_archive"),
    path("setup/<int:pk>/share/", balance_setup_views.setup_share, name="setup_share"),
    path("mine/", balance_setup_views.setups_list, name="setups_list"),

    # Блок 7 (сравнение сетапов, ТЗ §8.1).
    path("compare/", balance_setup_views.setups_compare, name="setups_compare"),
]
