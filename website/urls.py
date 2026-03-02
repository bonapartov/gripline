from django.urls import path, include
from .views import DriverViewSet, TeamViewSet, TrackViewSet, track_detail_view, ChassisViewSet, drivers_api, chassis_detail_view, TyreBrandViewSet, TyreTypeViewSet, TyreViewSet, EngineViewSet
from .import_utils import import_preview, import_confirm
from wagtail.api.v2.views import PagesAPIViewSet
from wagtail.api.v2.router import WagtailAPIRouter
from . import views
from .views import compare_view, top_drivers_view, compare_models_view, weights_table_view, chassis_track_matrix_view, weather_impact_view
from .api import pulse_data  # Импортируем функцию напрямую
from .views import teams_api, chassis_api

driver_viewset = DriverViewSet()
team_viewset = TeamViewSet()
track_viewset = TrackViewSet()
chassis_viewset = ChassisViewSet()
tyrebrand_viewset = TyreBrandViewSet()
tyretype_viewset = TyreTypeViewSet()
tyre_viewset = TyreViewSet()
engine_viewset = EngineViewSet()

# Создаем API router только для стандартных эндпоинтов
api_router = WagtailAPIRouter('wagtailapi')
api_router.register_endpoint('pages', PagesAPIViewSet)
# Не регистрируем pulse здесь, добавим отдельным путем

urlpatterns = [
    path("drivers/", include(driver_viewset.get_urlpatterns())),
    path("teams/", include((team_viewset.get_urlpatterns(), 'website'), namespace='teams')),
    path("tracks/", include((track_viewset.get_urlpatterns(), 'website'), namespace='tracks')),
    path("chassis/", include((chassis_viewset.get_urlpatterns(), 'website'), namespace='chassis')),
    path("tyrebrands/", include((tyrebrand_viewset.get_urlpatterns(), 'website'), namespace='tyrebrands')),
    path("tyretypes/", include((tyretype_viewset.get_urlpatterns(), 'website'), namespace='tyretypes')),
    path("tyres/", include((tyre_viewset.get_urlpatterns(), 'website'), namespace='tyres')),
    path("engines-list/", include((engine_viewset.get_urlpatterns(), 'website'), namespace='engines_list')),
    path("import/preview/", import_preview, name="event_import_preview"),
    path("import/confirm/", import_confirm, name="event_import_confirm"),
    path("compare/", compare_view, name="compare"),
    path("top/drivers/", top_drivers_view, name="top_drivers"),
    path("compare-models/", compare_models_view, name="compare_models"),
    path("weights-table/", weights_table_view, name="weights_table"),
    path("matrix/", chassis_track_matrix_view, name="chassis_track_matrix"),
    path("weather-impact/", weather_impact_view, name="weather_impact"),
    path("drivers-api/", drivers_api, name="drivers_api"),
    path('api/v2/', include([
    path('pages/', api_router.urls),  # Стандартный API Wagtail
    path('pulse/', pulse_data, name='pulse_api'),  # Наш кастомный эндпоинт
    path('teams-api/', views.teams_api, name='teams_api'),
    path('chassis-api/', views.chassis_api, name='chassis_api'),
    ])),
]
