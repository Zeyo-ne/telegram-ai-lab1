"""OpenAI-совместимый HTTP-клиент без записи текста запроса и ответа в логи."""

import asyncio
import json
import logging
import ssl
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

import aiohttp
import certifi

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Содержит только заранее заданное безопасное сообщение пользователю."""


@dataclass(frozen=True)
class Completion:
    text: str
    usage: dict


class LanguageModel(Protocol):
    async def complete(self, messages: list[dict[str, str]], temperature: float) -> Completion: ...


class HTTPModel:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession | None = None):
        self.settings = settings
        self._owned = session is None
        self.session = session or aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=settings.llm_timeout),
            connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())),
        )

    async def close(self) -> None:
        if self._owned:
            await self.session.close()

    async def complete(self, messages: list[dict[str, str]], temperature: float) -> Completion:
        request_id = uuid.uuid4().hex[:12]
        started = time.monotonic()
        logger.info("LLM start id=%s model=%s", request_id, self.settings.llm_model)
        result = "error"
        try:
            async with asyncio.timeout(self.settings.llm_timeout):
                completion = await self._request(messages, temperature)
            result = "ok"
            return completion
        except TimeoutError:
            raise LLMError("Модель не успела ответить. Попробуй ещё раз немного позже.") from None
        finally:
            logger.info(
                "LLM end id=%s model=%s result=%s seconds=%.2f",
                request_id,
                self.settings.llm_model,
                result,
                time.monotonic() - started,
            )

    async def _request(self, messages: list[dict[str, str]], temperature: float) -> Completion:
        settings = self.settings
        payload = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": settings.llm_max_tokens,
            "stream": False,
        }
        # Запрещаем маршрутизацию к провайдеру, молча игнорирующему temperature.
        if settings.llm_base_url.startswith("https://openrouter.ai/"):
            payload["provider"] = {"require_parameters": True}
        for attempt in range(settings.llm_retries + 1):
            try:
                async with self.session.post(
                    settings.llm_base_url + "/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    allow_redirects=False,
                ) as response:
                    status = response.status
                    if status in {401, 403}:
                        raise LLMError("Сервис отклонил ключ модели. Проверь настройки доступа.")
                    if status == 402:
                        raise LLMError("Сервис модели отклонил запрос из-за баланса или лимита.")
                    if status == 429 or 500 <= status <= 599:
                        if attempt < settings.llm_retries:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        raise LLMError(
                            "Сервис модели временно недоступен или перегружен. Попробуй позже."
                        )
                    if status != 200:
                        raise LLMError(
                            "Сервис не принял запрос. Проверь выбранную модель и настройки."
                        )
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) > 2_000_000:
                            raise LLMError("Ответ сервиса слишком большой. Сократи запрос.")
                    try:
                        data = json.loads(body)
                        choice = data["choices"][0]
                        text = choice["message"]["content"]
                        if choice.get("finish_reason") not in {None, "stop", "end_turn"}:
                            raise LLMError(
                                "Ответ модели оборвался или был отклонён. Сократи запрос."
                            )
                        if not isinstance(text, str) or not text.strip():
                            raise ValueError
                        usage = data.get("usage") or {}
                        if not isinstance(usage, dict):
                            usage = {}
                    except (ValueError, KeyError, IndexError, TypeError):
                        raise LLMError(
                            "Модель вернула пустой или некорректный ответ. Попробуй снова."
                        ) from None
                    return Completion(text=text, usage=usage)
            except aiohttp.ClientError:
                if attempt < settings.llm_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise LLMError(
                    "Не удалось связаться с моделью. Проверь интернет и попробуй позже."
                ) from None
        raise LLMError("Сервис модели временно недоступен.")
