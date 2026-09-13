"""Weather integration boundary for location-configured Open-Meteo polling."""

from app.providers.weather.router import router
from app.providers.weather.service import weather_state
from app.providers.weather.source import WeatherPollSource, build_weather_source

__all__ = ["WeatherPollSource", "build_weather_source", "router", "weather_state"]
