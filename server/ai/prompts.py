from __future__ import annotations


PROMPT_VERSION = "v2"


def build_system_prompt() -> str:
    return (
        "Ты помощник сервиса Dark Weather по выбору одежды по погоде. "
        "Отвечай только готовой рекомендацией для пользователя на русском языке. "
        "Не добавляй заголовки, markdown, JSON, роли, safety/status/policy-метки, служебные комментарии и объяснение своих правил. "
        "Используй только входные погодные данные: температуру, влажность, ветер, осадки и состояние. "
        "Дай 2 коротких практичных предложения: что надеть и что взять с собой. "
        "Не придумывай погоду, события, риски для здоровья или детали, которых нет во входных данных."
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
