from __future__ import annotations

import json
import re


ROLE_TAG_RE = re.compile(r"</?(assistant|user|system|developer)>", re.IGNORECASE)
ROLE_PREFIX_RE = re.compile(r"^\s*(assistant|user|system|developer)\s*:\s*", re.IGNORECASE)
TECHNICAL_LINE_RE = re.compile(
    r"^\s*(user\s+safety|system\s+safety|assistant\s+safety|safety|policy|metadata|status|analysis|confidence)\s*:?.*$",
    re.IGNORECASE,
)
CLOTHING_RE = re.compile(
    r"(надень|одень|куртк|пальто|плащ|ветровк|свитер|худи|футболк|рубашк|брюк|джинс|обув|ботин|кроссов|зонт|шарф|перчат|шапк|сло)",
    re.IGNORECASE,
)
WET_WEATHER_ADVICE_RE = re.compile(r"(зонт|дожд|ливн|непромока|намок|мокр|снег|слякот)", re.IGNORECASE)
WET_CONDITION_RE = re.compile(r"(rain|drizzle|shower|snow|sleet|thunder|дожд|ливн|снег|осад)", re.IGNORECASE)
TOO_LIGHT_FOR_COLD_RE = re.compile(r"(шорт|майк|футболк|сандал|сланц)", re.IGNORECASE)
TOO_HEAVY_FOR_WARM_RE = re.compile(r"(пуховик|зимн|перчат|шапк|термобель)", re.IGNORECASE)


def _extract_json_text(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith("{"):
        return value

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return value

    if not isinstance(payload, dict):
        return value

    for key in ("recommendation", "advice", "text", "message"):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate

    return value


def clean_recommendation_text(value: str | None) -> str:
    if not value:
        return ""

    text = _extract_json_text(str(value))
    text = ROLE_TAG_RE.sub("", text)

    lines: list[str] = []
    for line in text.replace("\r", "\n").split("\n"):
        stripped = ROLE_PREFIX_RE.sub("", line.strip())
        if not stripped:
            continue
        if TECHNICAL_LINE_RE.match(stripped):
            continue
        if stripped.lower() in {"safe", "unsafe", "ok", "user safety: safe"}:
            continue
        lines.append(stripped)

    return re.sub(r"\s{2,}", " ", " ".join(lines)).strip()


def is_recommendation_usable(value: str) -> bool:
    if len(value) < 24:
        return False
    if TECHNICAL_LINE_RE.search(value):
        return False
    if not re.search(r"[A-Za-zА-Яа-я]", value):
        return False
    if not CLOTHING_RE.search(value) and len(value) < 90:
        return False
    return True


def is_recommendation_consistent_with_weather(
    value: str,
    *,
    temperature_c: float,
    precipitation_mm: float,
    condition: str = "",
) -> bool:
    if not value:
        return False

    has_wet_weather = float(precipitation_mm) > 0 or bool(WET_CONDITION_RE.search(condition or ""))
    if not has_wet_weather and WET_WEATHER_ADVICE_RE.search(value):
        return False

    temp = float(temperature_c)
    if temp <= 8 and TOO_LIGHT_FOR_COLD_RE.search(value):
        return False
    if temp >= 22 and TOO_HEAVY_FOR_WARM_RE.search(value):
        return False

    return True


def build_fallback_recommendation(
    *,
    city: str,
    temperature_c: float,
    humidity: float,
    wind_speed_ms: float,
    precipitation_mm: float,
    condition: str = "",
) -> str:
    temp = float(temperature_c)
    wind = float(wind_speed_ms)
    rain = float(precipitation_mm)
    humid = float(humidity)

    if temp <= -10:
        base = "выбирайте очень тёплую куртку, шапку, шарф, перчатки и утеплённую обувь"
    elif temp <= 0:
        base = "подойдёт зимняя куртка, шапка и тёплая закрытая обувь"
    elif temp <= 8:
        base = "наденьте тёплую куртку или пальто, свитер и закрытую обувь"
    elif temp <= 16:
        base = "лучше выбрать лёгкую куртку или ветровку и удобную закрытую обувь"
    elif temp <= 24:
        base = "будет комфортно в лёгкой одежде, но тонкая кофта пригодится вечером"
    else:
        base = "выбирайте лёгкую дышащую одежду и удобную обувь"

    details: list[str] = []
    if rain > 0:
        details.append("возьмите зонт или непромокаемую куртку")
    if wind >= 8:
        details.append("из-за ветра лучше добавить шарф или ветровку")
    elif wind >= 5:
        details.append("ветровка поможет чувствовать себя комфортнее")
    if humid >= 80 and temp <= 18:
        details.append("из-за влажности может ощущаться прохладнее")

    city_text = f"В городе {city}" if city else "Сейчас"
    suffix = "; ".join(details) if details else "без лишних слоёв, но с запасом на вечер"
    return f"{city_text} около {temp:.0f} °C: {base}. {suffix.capitalize()}."
