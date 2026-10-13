"""Сценарии диалога. Один пользователь обрабатывается последовательно."""

import asyncio
import math
from weakref import WeakValueDictionary

from app.config import Settings
from app.history import build_context
from app.llm import LanguageModel
from app.prompts import MODES, instructions
from app.storage import Repository

TEMPERATURES = (0.0, 0.3, 0.7, 1.0)


class Assistant:
    def __init__(self, repository: Repository, model: LanguageModel, settings: Settings):
        self.repository, self.model, self.settings = repository, model, settings
        self._locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()

    def lock(self, chat_id: int) -> asyncio.Lock:
        # Сильная ссылка удерживается async with, завершённые чаты не накапливаются.
        lock = self._locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[chat_id] = lock
        return lock

    async def reply(self, chat_id: int, text: str) -> str:
        async with self.lock(chat_id):
            profile = await self.repository.profile(chat_id)
            turns = await self.repository.history(chat_id)
            messages = build_context(instructions(profile.mode), turns, text, self.settings)
            result = await self.model.complete(messages, profile.temperature)
            await self.repository.save_turn(chat_id, text, result.text)
            return result.text

    async def mode(self, chat_id: int, mode: str) -> str:
        if mode not in MODES:
            raise ValueError("Неизвестный режим.")
        async with self.lock(chat_id):
            await self.repository.profile(chat_id)
            await self.repository.set_mode(chat_id, mode)
        return f"Режим: {MODES[mode].title}. Предыдущая история очищена."

    async def reset(self, chat_id: int) -> str:
        async with self.lock(chat_id):
            await self.repository.reset(chat_id)
        return "История очищена. Режим и temperature сохранены."

    async def settings_text(self, chat_id: int, value: str | None = None) -> str:
        selected = None
        if value is not None:
            try:
                selected = float(value.strip())
                if not math.isfinite(selected) or selected not in TEMPERATURES:
                    raise ValueError
            except ValueError:
                return "Допустимые значения: 0.0, 0.3, 0.7, 1.0. Пример: /settings 0.7"
        async with self.lock(chat_id):
            await self.repository.profile(chat_id)
            if selected is not None:
                await self.repository.set_temperature(chat_id, selected)
            profile = await self.repository.profile(chat_id)
        return (
            f"Режим: {MODES[profile.mode].title}\nМодель: {self.settings.llm_model}\n"
            f"temperature: {profile.temperature:.1f}\n"
            "Изменить: /settings 0.0, /settings 0.3, /settings 0.7 или /settings 1.0"
        )
