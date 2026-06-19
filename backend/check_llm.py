from __future__ import annotations

from app.llm.client import OpenAICompatibleClient
from app.llm.settings import get_llm_settings


def main() -> None:
    settings = get_llm_settings()
    print(f"mode={settings.mode}")
    print(f"base_url_configured={bool(settings.base_url)}")
    print(f"api_key_configured={bool(settings.api_key)}")
    print(f"model={settings.model}")
    print(f"chat_url={settings.chat_completions_url}")

    client = OpenAICompatibleClient(settings)
    response = client.chat(
        [
            {
                "role": "system",
                "content": "You are a concise API connectivity checker. Reply in JSON only.",
            },
            {
                "role": "user",
                "content": "Return {\"ok\": true, \"message\": \"connected\"}.",
            },
        ],
        temperature=0,
    )
    print(response)


if __name__ == "__main__":
    main()
