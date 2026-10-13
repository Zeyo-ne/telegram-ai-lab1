"""Параметризованные SQL-запросы; пара сообщений сохраняется атомарно."""

from dataclasses import dataclass
from typing import Protocol

import asyncpg

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab1_profiles (
    chat_id BIGINT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'study' CHECK (mode IN ('study', 'translate', 'quiz')),
    temperature DOUBLE PRECISION NOT NULL DEFAULT 0.3 CHECK (temperature IN (0, 0.3, 0.7, 1))
);
CREATE TABLE IF NOT EXISTS lab1_turns (
    id BIGSERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL REFERENCES lab1_profiles(chat_id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lab1_turns_chat_id_id ON lab1_turns(chat_id, id);
"""


@dataclass(frozen=True)
class Profile:
    mode: str = "study"
    temperature: float = 0.3


class Repository(Protocol):
    async def profile(self, chat_id: int) -> Profile: ...
    async def history(self, chat_id: int) -> list[tuple[str, str]]: ...
    async def set_mode(self, chat_id: int, mode: str) -> None: ...
    async def set_temperature(self, chat_id: int, value: float) -> None: ...
    async def reset(self, chat_id: int) -> None: ...
    async def save_turn(self, chat_id: int, question: str, answer: str) -> None: ...


class PostgresRepository:
    def __init__(self, pool: asyncpg.Pool, max_messages: int):
        self.pool = pool
        self.max_turns = max_messages // 2

    async def initialize(self) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            # Сериализует создание схемы двумя одновременно запущенными процессами.
            await connection.execute("SELECT pg_advisory_xact_lock(7100101)")
            await connection.execute(SCHEMA)

    async def profile(self, chat_id: int) -> Profile:
        await self.pool.execute(
            "INSERT INTO lab1_profiles(chat_id) VALUES ($1) ON CONFLICT DO NOTHING", chat_id
        )
        row = await self.pool.fetchrow(
            "SELECT mode, temperature FROM lab1_profiles WHERE chat_id=$1", chat_id
        )
        return Profile(row["mode"], row["temperature"])

    async def history(self, chat_id: int) -> list[tuple[str, str]]:
        rows = await self.pool.fetch(
            "SELECT question, answer FROM "
            "(SELECT id, question, answer FROM lab1_turns WHERE chat_id=$1 "
            "ORDER BY id DESC LIMIT $2) AS recent ORDER BY id",
            chat_id,
            self.max_turns,
        )
        return [(row["question"], row["answer"]) for row in rows]

    async def set_mode(self, chat_id: int, mode: str) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "UPDATE lab1_profiles SET mode=$2 WHERE chat_id=$1", chat_id, mode
            )
            await connection.execute("DELETE FROM lab1_turns WHERE chat_id=$1", chat_id)

    async def set_temperature(self, chat_id: int, value: float) -> None:
        await self.pool.execute(
            "UPDATE lab1_profiles SET temperature=$2 WHERE chat_id=$1", chat_id, value
        )

    async def reset(self, chat_id: int) -> None:
        await self.pool.execute("DELETE FROM lab1_turns WHERE chat_id=$1", chat_id)

    async def save_turn(self, chat_id: int, question: str, answer: str) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO lab1_turns(chat_id, question, answer) VALUES ($1, $2, $3)",
                chat_id,
                question,
                answer,
            )
            await connection.execute(
                "DELETE FROM lab1_turns WHERE chat_id=$1 AND id NOT IN "
                "(SELECT id FROM lab1_turns WHERE chat_id=$1 ORDER BY id DESC LIMIT $2)",
                chat_id,
                self.max_turns,
            )
