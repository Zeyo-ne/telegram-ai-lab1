"""Мастер первого запуска. Реальные ключи вводятся только на компьютере владельца."""

import getpass
import json
import ssl
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import certifi
from dotenv import dotenv_values, set_key

from app.config import ConfigError, Settings
from scripts.local import prepare_env

ROOT = Path(__file__).resolve().parents[1]


def choose_model() -> str:
    print("Ищем бесплатные модели OpenRouter с поддержкой temperature…")
    models = []
    try:
        with urlopen(
            "https://openrouter.ai/api/v1/models",
            timeout=15,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            data = json.load(response)
        models = [
            model
            for model in data["data"]
            if model["id"].endswith(":free")
            and "temperature" in model.get("supported_parameters", [])
            and model.get("context_length", 0) >= 24000
        ][:10]
    except (URLError, TimeoutError, ValueError, KeyError, TypeError):
        print("Список моделей не загрузился. Можно ввести идентификатор вручную.")
    if models:
        for number, model in enumerate(models, 1):
            print(f"{number}. {model['name']} ({model['id']})")
        print("Выбери номер или введи точный идентификатор другой модели.")
        choice = input("Модель (Enter — первая бесплатная из списка): ").strip() or "1"
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            return models[int(choice) - 1]["id"]
        return choice
    print("Идентификатор модели можно скопировать со страницы https://openrouter.ai/models")
    return input("Модель (обязательна поддержка temperature): ").strip()


def main() -> int:
    try:
        path = prepare_env(ROOT, cloud=False)
        values = dotenv_values(path, interpolate=False)
        if not values.get("LLM_BASE_URL"):
            set_key(path, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
        if not values.get("LLM_API_KEY"):
            print("Создай ключ на https://openrouter.ai/keys и скопируй его.")
            key = getpass.getpass("Ключ модели (ввод скрыт): ").strip()
            if not key:
                raise ConfigError("Ключ не введён. Запусти настройку снова, когда он будет готов.")
            set_key(path, "LLM_API_KEY", key)
        if not values.get("LLM_MODEL"):
            set_key(path, "LLM_MODEL", choose_model())
        path.chmod(0o600)
        settings = Settings.load(path)
        settings.require_llm()
        print(f"Настройка готова. Выбранная модель: {settings.llm_model}")
        return 0
    except (ConfigError, OSError) as exc:
        # OSError может содержать локальный путь, но не печатаем произвольные исключения.
        print(str(exc) if isinstance(exc, ConfigError) else "Не удалось сохранить настройки.")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Настройка прервана; введённые ранее значения сохранены локально.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
