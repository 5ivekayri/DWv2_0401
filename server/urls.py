from django.urls import path
from .views import WeatherView, health

urlpatterns = [
    path("weather", WeatherView.as_view()),
    path("health", health),
]
