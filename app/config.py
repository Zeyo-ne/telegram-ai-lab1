"""Единственное место чтения и проверки настроек приложения."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import dotenv_values


class ConfigError(ValueError):
    """Ошибка настройки без секретных значений в сообщении."""


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    postgres_password: str = field(repr=False)
    telegram_proxy_url: str = field(default="", repr=False)
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "bot"
    postgres_user: str = "bot"
    log_level: str = "INFO"
    health_port: int = 8080
    llm_api_key: str = field(default="", repr=False)
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = ""
    llm_timeout: float = 60.0
    llm_max_tokens: int = 1200
    llm_retries: int = 1
    history_max_messages: int = 20
    context_max_units: int = 24000
    input_max_chars: int = 12000

    def require_llm(self) -> None:
        if not self.llm_api_key:
            raise ConfigError("LLM_API_KEY: укажите ключ выбранного сервиса модели.")
        if not self.llm_model:
            raise ConfigError("LLM_MODEL: укажите точный идентификатор модели.")

    @classmethod
    def load(
        cls, env_file: Path | str = ".env", *, environ: Mapping[str, str] | None = None
    ) -> "Settings":
        values = {
            **dotenv_values(env_file, interpolate=False),
            **(os.environ if environ is None else environ),
        }

        def value(key: str, default: str = "") -> str:
            return values.get(key) or default

        def port(key: str, default: str) -> int:
            try:
                result = int(value(key, default))
                if not 1 <= result <= 65535:
                    raise ValueError
                return result
            except ValueError:
                raise ConfigError(f"{key}: нужен номер порта от 1 до 65535.") from None

        def integer(key: str, default: str, lower: int, upper: int) -> int:
            try:
                result = int(value(key, default))
                if not lower <= result <= upper:
                    raise ValueError
                return result
            except ValueError:
                raise ConfigError(f"{key}: нужно целое число от {lower} до {upper}.") from None

        try:
            llm_timeout = float(value("LLM_TIMEOUT", "60"))
            if not math.isfinite(llm_timeout) or not 1 <= llm_timeout <= 180:
                raise ValueError
        except ValueError:
            raise ConfigError("LLM_TIMEOUT: нужно число от 1 до 180.") from None
        base_url = value("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        try:
            parsed_url = urlsplit(base_url)
            if (
                parsed_url.scheme not in {"https", "http"}
                or not parsed_url.hostname
                or parsed_url.username
                or parsed_url.password
                or parsed_url.query
                or parsed_url.fragment
                or (
                    parsed_url.scheme == "http"
                    and parsed_url.hostname not in {"localhost", "127.0.0.1", "::1"}
                )
            ):
                raise ValueError
            _ = parsed_url.port
        except ValueError:
            raise ConfigError("LLM_BASE_URL: нужен HTTPS-адрес API без ключей и паролей.") from None
        model = value("LLM_MODEL")
        if len(model) > 200 or any(char.isspace() for char in model):
            raise ConfigError("LLM_MODEL: нужен идентификатор модели без пробелов.")

        token = value("BOT_TOKEN")
        try:
            validate_token(token)
        except TokenValidationError:
            raise ConfigError("BOT_TOKEN: укажите токен, полученный у BotFather.") from None
        password = value("POSTGRES_PASSWORD")
        if not password:
            raise ConfigError("POSTGRES_PASSWORD: пароль базы данных не задан.")
        proxy = value("TELEGRAM_PROXY_URL")
        if proxy:
            try:
                parsed = urlsplit(proxy)
                if (
                    parsed.scheme not in {"http", "socks5"}
                    or not parsed.hostname
                    or not parsed.port
                    or parsed.path not in {"", "/"}
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError
            except ValueError:
                raise ConfigError(
                    "TELEGRAM_PROXY_URL: нужен http://host:port или socks5://host:port; "
                    "при необходимости добавьте user:password@."
                ) from None
        level = value("LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("LOG_LEVEL: используйте DEBUG, INFO, WARNING, ERROR или CRITICAL.")
        return cls(
            bot_token=token,
            postgres_password=password,
            telegram_proxy_url=proxy,
            postgres_host=value("POSTGRES_HOST", "127.0.0.1"),
            postgres_port=port("POSTGRES_PORT", "5432"),
            postgres_db=value("POSTGRES_DB", "bot"),
            postgres_user=value("POSTGRES_USER", "bot"),
            log_level=level,
            health_port=port("HEALTH_PORT", "8080"),
            llm_api_key=value("LLM_API_KEY"),
            llm_base_url=base_url,
            llm_model=model,
            llm_timeout=llm_timeout,
            llm_max_tokens=integer("LLM_MAX_TOKENS", "1200", 100, 8000),
            llm_retries=integer("LLM_RETRIES", "1", 0, 2),
            history_max_messages=integer("HISTORY_MAX_MESSAGES", "20", 2, 100),
            context_max_units=integer("CONTEXT_MAX_UNITS", "24000", 4000, 200000),
            input_max_chars=integer("INPUT_MAX_CHARS", "12000", 100, 20000),
        )
