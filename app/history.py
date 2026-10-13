"""Сокращение только целых пар, без потери инструкции и текущего запроса."""

from app.config import Settings


class ContextError(ValueError):
    pass


def estimated_units(messages: list[dict[str, str]]) -> int:
    # Консервативная оценка: один UTF-8 байт = одна единица + запас на роли.
    # Это не точный tokenizer конкретной модели; лимит задаётся пользователем.
    return sum(len(message["content"].encode("utf-8")) + 16 for message in messages)


def build_context(
    prefix: list[dict[str, str]],
    turns: list[tuple[str, str]],
    current: str,
    settings: Settings,
) -> list[dict[str, str]]:
    if not current.strip():
        raise ContextError("Отправь непустой текст.")
    if len(current) > settings.input_max_chars:
        raise ContextError("Сообщение слишком длинное. Раздели его на несколько вопросов.")
    tail = {"role": "user", "content": current}
    budget = settings.context_max_units - settings.llm_max_tokens
    if estimated_units([*prefix, tail]) > budget:
        raise ContextError("Сообщение не помещается в контекст модели. Сократи вопрос.")
    recent = list(turns[-(settings.history_max_messages // 2) :])
    while True:
        history = [
            {"role": role, "content": text}
            for question, answer in recent
            for role, text in (("user", question), ("assistant", answer))
        ]
        result = [*prefix, *history, tail]
        if estimated_units(result) <= budget:
            return result
        recent.pop(0)


def split_reply(text: str, limit: int = 4096) -> list[str]:
    """Telegram считает UTF-16 единицы, в частности emoji занимают две."""
    if limit < 2:
        raise ValueError("limit must be at least 2")
    parts, part, size = [], [], 0
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if size + units > limit:
            parts.append("".join(part))
            part, size = [], 0
        part.append(char)
        size += units
    if part:
        parts.append("".join(part))
    return parts
