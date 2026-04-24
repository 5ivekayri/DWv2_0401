from django.urls import path

from .views import health, WeatherView, AIOutfitRecommendationView

urlpatterns = [
    path("health", health, name="health"),
    path("weather", WeatherView.as_view(), name="weather"),
    path("ai/outfit-recommendation", AIOutfitRecommendationView.as_view(), name="ai_outfit_recommendation"),
]