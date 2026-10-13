"""14 реальных вызовов: 12 для temperature и 2 для сравнения промптов."""

import asyncio
import csv
import json
import re
import secrets
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app.assistant import TEMPERATURES, Assistant
from app.config import ConfigError, Settings
from app.db import create_pool
from app.llm import HTTPModel, LLMError
from app.logging_setup import configure_logging
from app.prompts import MODES
from app.storage import PostgresRepository

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "Объясни разницу между списком и кортежем в Python в трёх нумерованных пунктах."


class RecordingModel:
    def __init__(self, model):
        self.model = model
        self.last = None

    async def complete(self, messages, temperature):
        self.last = await self.model.complete(messages, temperature)
        return self.last


async def run(settings: Settings, folder: Path) -> dict:
    settings.require_llm()
    pool = await create_pool(settings)
    model = None
    chat_id = -(secrets.randbelow(2**60) + 1)
    result = {
        "status": "partial",
        "date": datetime.now().astimezone().isoformat(),
        "question": QUESTION,
        "system_prompt": MODES["study"].system,
        "model": settings.llm_model,
        "max_tokens": settings.llm_max_tokens,
        "criteria": [
            "Ровно три нумерованных пункта",
            "Различие изменяемости объяснено верно",
            "Ответ понятен начинающему, нет выдуманных фактов",
        ],
        "runs": [],
        "prompt_comparison": [],
    }
    await asyncio.to_thread(folder.mkdir, exist_ok=True)

    def save():
        (folder / "experiment.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    try:
        repository = PostgresRepository(pool, settings.history_max_messages)
        await repository.initialize()
        # Повтор HTTP отключён: каждый запуск эксперимента — один независимый запрос.
        model = HTTPModel(replace(settings, llm_retries=0))
        recorder = RecordingModel(model)
        assistant = Assistant(repository, recorder, settings)
        await assistant.mode(chat_id, "study")
        for temperature in TEMPERATURES:
            await assistant.settings_text(chat_id, str(temperature))
            for repeat in range(1, 4):
                # Используется тот же сценарий, что и команда /reset в боте.
                await assistant.reset(chat_id)
                answer = await assistant.reply(chat_id, QUESTION)
                row = {
                    "number": len(result["runs"]) + 1,
                    "temperature": temperature,
                    "repeat": repeat,
                    "length": len(answer),
                    "answer": answer,
                    "usage": recorder.last.usage,
                    "format_ok": "да"
                    if re.findall(r"(?m)^\s*(?:\*\*)?([0-9]+)[.)]\s", answer) == ["1", "2", "3"]
                    else "нет",
                    "observations": (
                        f"Длина {len(answer)} символов; "
                        "точность содержания оценивается по сохранённому ответу."
                    ),
                }
                result["runs"].append(row)
                save()
                print(f"Запрос {row['number']}/12 выполнен, temperature={temperature}.")
        for label, prompt in (
            ("Исходная неполная", "Помоги с Python."),
            ("Улучшенная", MODES["study"].system + " Дай ровно три нумерованных пункта."),
        ):
            completion = await model.complete(
                [{"role": "system", "content": prompt}, {"role": "user", "content": QUESTION}],
                0.3,
            )
            result["prompt_comparison"].append(
                {
                    "label": label,
                    "prompt": prompt,
                    "answer": completion.text,
                    "usage": completion.usage,
                }
            )
            save()
        result["status"] = "complete"
    except (LLMError, ConfigError) as exc:
        result["error"] = str(exc)
        raise
    finally:
        save()
        if model:
            await model.close()
        try:
            # Удаляется только временный профиль эксперимента; личные диалоги не затрагиваются.
            await pool.execute("DELETE FROM lab1_profiles WHERE chat_id=$1", chat_id)
        finally:
            await pool.close()
    with (folder / "experiment.csv").open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "number",
                "temperature",
                "repeat",
                "length",
                "format_ok",
                "observations",
                "answer",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(result["runs"])
    return result


def main() -> int:
    try:
        settings = Settings.load(ROOT / ".env")
        configure_logging(settings)
        asyncio.run(run(settings, ROOT / "reports"))
        print("Готово: reports/experiment.json и experiment.csv. Оцени реальные ответы в отчёте.")
        return 0
    except (ConfigError, LLMError) as exc:
        print(str(exc))
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception:
        print("Эксперимент не завершён. Проверь запуск БД и настройки; успешные ответы сохранены.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
