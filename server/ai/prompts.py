from __future__ import annotations


PROMPT_VERSION = "v1"


def build_system_prompt() -> str:
    return (
        "Ты ассистент по погоде и одежде. "
        "Дай короткую, дружелюбную и практичную рекомендацию, что надеть сегодня. "
        "Учитывай температуру, влажность, ветер, осадки и погодное состояние. "
        "Пиши на русском языке. "
        "Максимум 2-3 предложения. "
        "Не придумывай факты, которых нет во входных данных."
    )


def build_user_prompt(
    *,
    city: str,
    temperature_c: float,
    humidity: float,
    wind_speed_ms: float,
    precipitation_mm: float,
    condition: str | None = None,
) -> str:
    condition_text = condition or "unknown"

    return (
        f"Город: {city}\n"
        f"Температура: {temperature_c} °C\n"
        f"Влажность: {humidity} %\n"
        f"Ветер: {wind_speed_ms} м/с\n"
        f"Осадки: {precipitation_mm} мм\n"
        f"Состояние: {condition_text}\n\n"
        "Скажи, что лучше надеть сегодня."
    )