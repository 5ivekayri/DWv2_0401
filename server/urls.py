from django.urls import path

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
    path("geocode", GeocodeView.as_view(), name="geocode"),
    path("weather", WeatherView.as_view(), name="weather"),
    path("weather/history", WeatherHistoryView.as_view(), name="weather_history"),
    path("ai/outfit-recommendation", AIOutfitRecommendationView.as_view(), name="ai_outfit_recommendation"),
    path("station/readings", StationReadingIngestView.as_view(), name="station_reading_ingest"),
    path("station/latest", StationLatestView.as_view(), name="station_latest"),
    path("station/history", StationHistoryView.as_view(), name="station_history"),
]
