"""Реальная БД: RUN_INTEGRATION=1 python -m pytest -m integration -v."""

import os
from unittest.mock import AsyncMock

import pytest

from app.assistant import Assistant
from app.db import create_pool
from app.llm import Completion
from app.storage import PostgresRepository, Profile
from tests.test_integration import database as database_fixture

database = database_fixture
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1", reason="Нужен Docker и RUN_INTEGRATION=1"
    ),
]


async def test_real_postgres_restart_isolation_mode_reset_pruning_and_parameterized_sql(database):
    # Arrange: fixture запускает отдельную тестовую БД и удаляет только свои ресурсы.
    settings, _, _, _ = database
    pool = await create_pool(settings)
    try:
        repository = PostgresRepository(pool, max_messages=4)
        await repository.initialize()
        await repository.initialize()  # повторный запуск не уничтожает таблицы
        model = AsyncMock()
        model.complete.return_value = Completion("Настоящий сохранённый ответ 👋", {})
        assistant = Assistant(repository, model, settings)
        await assistant.settings_text(1, "0.7")
        await assistant.reply(1, "'); DROP TABLE lab1_profiles; --")
        await assistant.reply(2, "Второй пользователь")
    finally:
        await pool.close()
    # Act: новое соединение и новый сервис, не общая память тестового репозитория.
    pool = await create_pool(settings)
    try:
        repository = PostgresRepository(pool, max_messages=4)
        await repository.initialize()
        assistant = Assistant(repository, model, settings)
        # Assert
        assert await repository.profile(1) == Profile("study", 0.7)
        assert (await repository.history(1))[0][0] == "'); DROP TABLE lab1_profiles; --"
        assert (await repository.history(2))[0][0] == "Второй пользователь"
        await assistant.reply(1, "Второй вопрос")
        await assistant.reply(1, "Третий вопрос")
        assert [question for question, _ in await repository.history(1)] == [
            "Второй вопрос",
            "Третий вопрос",
        ]
        await assistant.mode(1, "translate")
        assert await repository.history(1) == []
        assert await repository.profile(1) == Profile("translate", 0.7)
        await assistant.reply(1, "На английский: привет")
        await assistant.reset(1)
        assert await repository.profile(1) == Profile("translate", 0.7)
        assert await repository.history(1) == []
        assert len(await repository.history(2)) == 1
    finally:
        await pool.close()
