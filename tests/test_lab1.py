import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, PhotoSize, Update, User

from app.assistant import Assistant
from app.config import ConfigError, Settings
from app.handlers.assistant import HELP, create_router
from app.history import ContextError, build_context, estimated_units, split_reply
from app.llm import Completion, LLMError
from app.logging_setup import configure_logging
from app.prompts import instructions
from app.storage import Profile

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"


class MemoryRepository:
    """Тестовая реализация порта; не используется в приложении."""

    def __init__(self, max_turns=10):
        self.profiles, self.turns = {}, {}
        self.max_turns = max_turns

    async def profile(self, chat_id):
        return self.profiles.setdefault(chat_id, Profile())

    async def history(self, chat_id):
        return list(self.turns.get(chat_id, []))

    async def set_mode(self, chat_id, mode):
        self.profiles[chat_id] = replace(self.profiles[chat_id], mode=mode)
        await self.reset(chat_id)

    async def set_temperature(self, chat_id, value):
        self.profiles[chat_id] = replace(self.profiles[chat_id], temperature=value)

    async def reset(self, chat_id):
        self.turns[chat_id] = []

    async def save_turn(self, chat_id, question, answer):
        self.turns.setdefault(chat_id, []).append((question, answer))
        self.turns[chat_id] = self.turns[chat_id][-self.max_turns :]


@pytest.fixture
def settings():
    return Settings(
        bot_token=TOKEN,
        postgres_password="test-db",
        llm_api_key="test-key",
        llm_model="test/model",
        llm_retries=0,
    )


@pytest.fixture
def assistant(settings):
    repository = MemoryRepository()
    model = AsyncMock()
    model.complete.return_value = Completion("Ответ модели", {"total_tokens": 10})
    return Assistant(repository, model, settings)


async def test_reply_has_roles_chronology_and_real_temperature(assistant):
    # Arrange
    await assistant.settings_text(1, "0.7")
    await assistant.reply(1, "Первый вопрос")
    # Act
    answer = await assistant.reply(1, "Уточнение")
    # Assert
    assert answer == "Ответ модели"
    args = assistant.model.complete.call_args.args
    assert args == (
        [
            *instructions("study"),
            {"role": "user", "content": "Первый вопрос"},
            {"role": "assistant", "content": "Ответ модели"},
            {"role": "user", "content": "Уточнение"},
        ],
        0.7,
    )


async def test_users_never_share_history_or_settings(assistant):
    # Arrange
    await assistant.reply(1, "Секрет первого")
    await assistant.settings_text(1, "1.0")
    # Act
    await assistant.reply(2, "Вопрос второго")
    # Assert
    messages, temperature = assistant.model.complete.call_args.args
    assert messages == [*instructions("study"), {"role": "user", "content": "Вопрос второго"}]
    assert temperature == 0.3
    assert len(await assistant.repository.history(1)) == 1


async def test_mode_clears_only_own_history_and_preserves_temperature(assistant):
    # Arrange
    await assistant.reply(1, "a")
    await assistant.reply(2, "b")
    await assistant.settings_text(1, "0.7")
    # Act
    text = await assistant.mode(1, "translate")
    # Assert
    assert text == "Режим: Перевод. Предыдущая история очищена."
    assert await assistant.repository.profile(1) == Profile("translate", 0.7)
    assert await assistant.repository.history(1) == []
    assert len(await assistant.repository.history(2)) == 1
    await assistant.reply(1, "На английский: привет")
    messages, _ = assistant.model.complete.call_args.args
    assert messages[:5] == instructions("translate")
    assert all(message["content"] != "a" for message in messages)


async def test_reset_preserves_own_settings_and_other_user(assistant):
    # Arrange
    await assistant.mode(1, "quiz")
    await assistant.settings_text(1, "1.0")
    await assistant.reply(1, "a")
    await assistant.reply(2, "b")
    # Act
    confirmation = await assistant.reset(1)
    # Assert
    assert confirmation == "История очищена. Режим и temperature сохранены."
    assert await assistant.repository.profile(1) == Profile("quiz", 1.0)
    assert await assistant.repository.history(1) == []
    assert len(await assistant.repository.history(2)) == 1


@pytest.mark.parametrize("value", ["0", "0.0", "0.3", "0.7", "1.0"])
async def test_allowed_temperature_applies_on_next_request(assistant, value):
    # Act
    text = await assistant.settings_text(1, value)
    await assistant.reply(1, "Вопрос")
    # Assert
    assert f"temperature: {float(value):.1f}" in text
    assert assistant.model.complete.call_args.args[1] == float(value)


@pytest.mark.parametrize("value", ["nan", "inf", "0.5", "-1", "2", "abc", "", "0,7"])
async def test_invalid_temperature_has_exact_error_and_no_api_call(assistant, value):
    # Act
    text = await assistant.settings_text(1, value)
    # Assert
    assert text == "Допустимые значения: 0.0, 0.3, 0.7, 1.0. Пример: /settings 0.7"
    assistant.model.complete.assert_not_called()
    assert await assistant.repository.profile(1) == Profile()


async def test_failed_llm_call_does_not_create_a_turn(assistant):
    # Arrange
    await assistant.reply(1, "Успешный")
    assistant.model.complete.side_effect = LLMError("Безопасная ошибка")
    # Act / Assert
    with pytest.raises(LLMError, match="Безопасная ошибка"):
        await assistant.reply(1, "Неуспешный")
    assert await assistant.repository.history(1) == [("Успешный", "Ответ модели")]


async def test_new_service_restores_existing_repository_state(assistant):
    # Arrange: отдельный тест постоянной БД находится в test_lab1_postgres.py.
    await assistant.mode(1, "quiz")
    await assistant.reply(1, "Списки")
    restarted = Assistant(assistant.repository, assistant.model, assistant.settings)
    # Act
    await restarted.reply(1, "Мой ответ")
    # Assert
    messages, _ = assistant.model.complete.call_args.args
    assert messages[0] == instructions("quiz")[0]
    assert messages[-3:] == [
        {"role": "user", "content": "Списки"},
        {"role": "assistant", "content": "Ответ модели"},
        {"role": "user", "content": "Мой ответ"},
    ]


async def test_reset_waits_for_in_flight_reply(assistant):
    # Arrange
    started, finish = asyncio.Event(), asyncio.Event()

    async def slow(*_):
        started.set()
        await finish.wait()
        return Completion("Ответ", {})

    assistant.model.complete.side_effect = slow
    reply = asyncio.create_task(assistant.reply(1, "Вопрос"))
    await started.wait()
    reset = asyncio.create_task(assistant.reset(1))
    await asyncio.sleep(0)
    # Act
    assert not reset.done()
    finish.set()
    await asyncio.gather(reply, reset)
    # Assert
    assert await assistant.repository.history(1) == []


def test_history_limit_removes_whole_old_turns(settings):
    # Arrange
    settings = replace(settings, history_max_messages=3)
    # Act
    messages = build_context(instructions("study"), [("old", "a"), ("new", "b")], "now", settings)
    # Assert
    assert messages[-3:] == [
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "now"},
    ]


def test_context_volume_limit_preserves_prefix_and_current_request(settings):
    # Arrange
    settings = replace(settings, context_max_units=1500, llm_max_tokens=100)
    prefix = [{"role": "system", "content": "Инструкция"}]
    turns = [("старый" * 200, "ответ" * 200), ("новый", "ответ")]
    # Act
    messages = build_context(prefix, turns, "текущий", settings)
    # Assert
    assert messages[0] == prefix[0]
    assert messages[-1] == {"role": "user", "content": "текущий"}
    assert len(messages) == 4
    assert estimated_units(messages) + settings.llm_max_tokens <= settings.context_max_units


@pytest.mark.parametrize("text", ["", "   ", "x" * 12001])
def test_reject_input_without_truncating_or_sending_it(settings, text):
    with pytest.raises(ContextError):
        build_context(instructions("study"), [], text, settings)


def test_current_question_and_prefix_cannot_exceed_budget(settings):
    with pytest.raises(ContextError, match="контекст"):
        build_context(
            instructions("study"),
            [],
            "Я" * 2000,
            replace(settings, context_max_units=2000, llm_max_tokens=100),
        )


@pytest.mark.parametrize(
    "text",
    ["x" * 10000, "👩‍💻" * 2500, "<b>*&" * 2000, "a\n" * 3000],
    ids=["ascii", "emoji", "markup", "newlines"],
)
def test_split_preserves_every_character_and_telegram_utf16_limit(text):
    parts = split_reply(text)
    assert "".join(parts) == text
    assert all(part and len(part.encode("utf-16-le")) // 2 <= 4096 for part in parts)


async def dispatch(assistant, content, *, chat_type="private", photo=False):
    bot = Bot(TOKEN)
    bot.session = AsyncMock()
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router())
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=42, type=chat_type),
        from_user=User(id=42, is_bot=False, first_name="Тест"),
        text=None if photo else content,
        photo=[PhotoSize(file_id="a", file_unique_id="b", width=1, height=1)] if photo else None,
    )
    await dispatcher.feed_update(bot, Update(update_id=1, message=message), assistant=assistant)
    return [
        call.args[1] for call in bot.session.call_args_list if isinstance(call.args[1], SendMessage)
    ]


async def test_start_router_returns_exact_help_without_calling_model(assistant):
    replies = await dispatch(assistant, "/start")
    assert len(replies) == 1 and replies[0].text == HELP
    assistant.model.complete.assert_not_called()


async def test_switch_command_is_not_sent_to_model(assistant):
    replies = await dispatch(assistant, "/quiz")
    assert replies[0].text == "Режим: Проверка знаний. Предыдущая история очищена."
    assert await assistant.repository.profile(42) == Profile("quiz", 0.3)
    assistant.model.complete.assert_not_called()


async def test_settings_command_rejects_invalid_before_model(assistant):
    replies = await dispatch(assistant, "/settings 0.5")
    assert replies[0].text == "Допустимые значения: 0.0, 0.3, 0.7, 1.0. Пример: /settings 0.7"
    assistant.model.complete.assert_not_called()


@pytest.mark.parametrize(
    "chat_type,photo", [("group", False), ("supergroup", False), ("private", True)]
)
async def test_nonprivate_or_nontext_messages_ignored(assistant, chat_type, photo):
    assert await dispatch(assistant, "Текст", chat_type=chat_type, photo=photo) == []
    assistant.model.complete.assert_not_called()


async def test_unknown_command_has_exact_safe_reply(assistant):
    replies = await dispatch(assistant, "/unknown")
    assert replies[0].text == "Неизвестная команда. Список команд: /start"
    assistant.model.complete.assert_not_called()


async def test_router_sends_long_answer_in_order_without_markup(assistant):
    answer = "👋" * 5000 + "<b>текст</b>"
    assistant.model.complete.return_value = Completion(answer, {})
    replies = await dispatch(assistant, "Вопрос")
    assert "".join(reply.text for reply in replies) == answer
    assert all(reply.parse_mode is None for reply in replies)
    assert all(len(reply.text.encode("utf-16-le")) // 2 <= 4096 for reply in replies)


async def test_router_converts_llm_error_to_exact_user_message(assistant):
    assistant.model.complete.side_effect = LLMError("Модель не успела ответить. Попробуй позже.")
    replies = await dispatch(assistant, "Вопрос")
    assert replies[0].text == "Модель не успела ответить. Попробуй позже."
    assert await assistant.repository.history(42) == []


async def test_unknown_failure_never_leaks_database_detail(assistant, caplog):
    assistant.repository.history = AsyncMock(side_effect=ValueError("secret-dialogue"))
    with caplog.at_level(logging.ERROR):
        replies = await dispatch(assistant, "user-secret")
    assert replies[0].text == "Не удалось обработать сообщение. Попробуй немного позже."
    assert "secret-dialogue" not in caplog.text
    assert "user-secret" not in caplog.text


async def test_command_database_failure_has_safe_reply_without_traceback(assistant, caplog):
    assistant.repository.set_mode = AsyncMock(side_effect=ValueError("private-data"))
    with caplog.at_level(logging.ERROR):
        replies = await dispatch(assistant, "/quiz")
    assert replies[0].text == "Не удалось обработать сообщение. Попробуй немного позже."
    assert "private-data" not in caplog.text
    assistant.model.complete.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("LLM_TIMEOUT", "nan"),
        ("LLM_TIMEOUT", "inf"),
        ("LLM_TIMEOUT", "0"),
        ("HISTORY_MAX_MESSAGES", "1"),
        ("LLM_RETRIES", "100"),
        ("LLM_BASE_URL", "https://user:password@server/v1"),
        ("LLM_BASE_URL", "http://outside.example/v1"),
        ("LLM_BASE_URL", "https://server/v1?key=secret"),
        ("LLM_MODEL", "bad model"),
    ],
)
def test_llm_configuration_rejects_bad_values_without_leaks(tmp_path, field, value):
    with pytest.raises(ConfigError) as caught:
        Settings.load(
            tmp_path / ".env",
            environ={
                "BOT_TOKEN": TOKEN,
                "POSTGRES_PASSWORD": "password",
                field: value,
            },
        )
    assert field in str(caught.value)
    assert "password" not in str(caught.value) and "secret" not in str(caught.value)


def test_llm_key_hidden_in_repr_and_logs(settings, capsys):
    configure_logging(settings)
    try:
        logging.getLogger("test-key").warning("Key: %s", settings.llm_api_key)
        assert "test-key" not in capsys.readouterr().err.split("Key:")[-1]
        assert "test-key" not in repr(settings)
    finally:
        logging.getLogger().handlers.clear()
