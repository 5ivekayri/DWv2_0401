from django.urls import path

from .admin_views import (
    AdminDashboardView,
    AdminIotStatusView,
    AdminLogsView,
    AdminProviderCheckView,
    AdminProvidersStatusView,
    AdminRaceStatsView,
)
from .views import (
    AIOutfitRecommendationView,
    GeocodeView,
    StationHistoryView,
    StationLatestView,
    StationReadingIngestView,
    WeatherHistoryView,
    WeatherView,
    health,
)

urlpatterns = [
    path("health", health, name="health"),
    path("admin/dashboard/", AdminDashboardView.as_view(), name="admin_dashboard"),
    path("admin/providers/status/", AdminProvidersStatusView.as_view(), name="admin_providers_status"),
    path("admin/providers/check/", AdminProviderCheckView.as_view(), name="admin_provider_check"),
    path("admin/race/stats/", AdminRaceStatsView.as_view(), name="admin_race_stats"),
    path("admin/iot/status/", AdminIotStatusView.as_view(), name="admin_iot_status"),
    path("admin/logs/", AdminLogsView.as_view(), name="admin_logs"),
    path("geocode", GeocodeView.as_view(), name="geocode"),
    path("geocode/", GeocodeView.as_view(), name="geocode_slash"),
    path("weather", WeatherView.as_view(), name="weather"),
    path("weather/", WeatherView.as_view(), name="weather_slash"),
    path("weather/history", WeatherHistoryView.as_view(), name="weather_history"),
    path("weather/history/", WeatherHistoryView.as_view(), name="weather_history_slash"),
    path("ai/outfit-recommendation", AIOutfitRecommendationView.as_view(), name="ai_outfit_recommendation"),
    path("ai/outfit-recommendation/", AIOutfitRecommendationView.as_view(), name="ai_outfit_recommendation_slash"),
    path("station/readings", StationReadingIngestView.as_view(), name="station_reading_ingest"),
    path("station/readings/", StationReadingIngestView.as_view(), name="station_reading_ingest_slash"),
    path("station/latest", StationLatestView.as_view(), name="station_latest"),
    path("station/latest/", StationLatestView.as_view(), name="station_latest_slash"),
    path("station/history", StationHistoryView.as_view(), name="station_history"),
    path("station/history/", StationHistoryView.as_view(), name="station_history_slash"),
]
