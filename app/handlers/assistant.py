import logging

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from app.assistant import Assistant
from app.history import ContextError, split_reply
from app.llm import LLMError

logger = logging.getLogger(__name__)


class SafeErrors(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as exc:
            logger.error("Message failed: %s", type(exc).__name__)
            try:
                await event.answer(
                    "Не удалось обработать сообщение. Попробуй немного позже.", parse_mode=None
                )
            except Exception as delivery_error:
                logger.error("Delivery failed: %s", type(delivery_error).__name__)


HELP = (
    "Я AI-помощник студента. Напиши вопрос — отвечу в текущем режиме.\n"
    "/study — объяснение программирования (режим по умолчанию)\n"
    "/translate — перевод; укажи язык в сообщении\n"
    "/quiz — проверка знаний; напиши тему\n"
    "/settings — настройки; например /settings 0.7\n"
    "/reset — очистить историю\n"
    "Ответы модели могут содержать ошибки: проверяй важные факты."
)


async def start(message: Message) -> None:
    await message.answer(HELP, parse_mode=None)


async def switch(message: Message, command: CommandObject, assistant: Assistant) -> None:
    await message.answer(await assistant.mode(message.chat.id, command.command), parse_mode=None)


async def reset(message: Message, assistant: Assistant) -> None:
    await message.answer(await assistant.reset(message.chat.id), parse_mode=None)


async def settings(message: Message, command: CommandObject, assistant: Assistant) -> None:
    await message.answer(
        await assistant.settings_text(message.chat.id, command.args), parse_mode=None
    )


async def unknown(message: Message) -> None:
    await message.answer("Неизвестная команда. Список команд: /start", parse_mode=None)


async def text(message: Message, assistant: Assistant) -> None:
    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            answer = await assistant.reply(message.chat.id, message.text)
    except (LLMError, ContextError) as exc:
        await message.answer(str(exc), parse_mode=None)
        return
    except Exception as exc:
        # Не записываем исключение БД: DETAIL может содержать пользовательский текст.
        logger.error("Dialogue failed: %s", type(exc).__name__)
        await message.answer(
            "Не удалось обработать сообщение. Попробуй немного позже.", parse_mode=None
        )
        return
    for part in split_reply(answer):
        await message.answer(part, parse_mode=None)


def create_router() -> Router:
    router = Router(name="lab1-assistant")
    router.message.filter(F.chat.type == "private", F.text)
    router.message.middleware(SafeErrors())
    router.message.register(start, Command("start", "help"))
    router.message.register(switch, Command("study", "translate", "quiz"))
    router.message.register(reset, Command("reset"))
    router.message.register(settings, Command("settings"))
    router.message.register(unknown, F.text.startswith("/"))
    router.message.register(text)
    return router
