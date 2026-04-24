from __future__ import annotations

import os
import requests


class OpenRouterClient:
    url = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.model_name = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip()

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def create_completion(self, *, system_prompt: str, user_prompt: str) -> tuple[str, str]:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is missing")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
        }

        response = requests.post(self.url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]

        return content.strip(), self.model_name