import json
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.llm import Completion, LLMError
from scripts import experiment
from scripts.report import render_report
from tests.test_lab1 import MemoryRepository


class FakePool:
    def __init__(self):
        self.execute, self.close = AsyncMock(), AsyncMock()


@pytest.fixture
def experiment_setup(monkeypatch):
    pool = FakePool()
    repository = MemoryRepository()
    repository.initialize = AsyncMock()
    model = AsyncMock()
    model.complete.return_value = Completion(
        "1. Первый\n2. Второй\n3. Третий", {"total_tokens": 12}
    )
    monkeypatch.setattr(experiment, "create_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(experiment, "PostgresRepository", lambda *_: repository)
    monkeypatch.setattr(experiment, "HTTPModel", lambda *_: model)
    config = Settings(
        bot_token="unused", postgres_password="unused", llm_api_key="unused", llm_model="test/model"
    )
    return config, pool, repository, model


async def test_experiment_executes_12_independent_requests_and_2_prompt_comparisons(
    experiment_setup, tmp_path
):
    # Arrange
    config, pool, repository, model = experiment_setup
    # Act
    result = await experiment.run(config, tmp_path)
    # Assert
    assert result["status"] == "complete"
    assert len(result["runs"]) == 12 and len(result["prompt_comparison"]) == 2
    assert model.complete.await_count == 14
    assert [call.args[1] for call in model.complete.call_args_list[:12]] == [
        0.0,
        0.0,
        0.0,
        0.3,
        0.3,
        0.3,
        0.7,
        0.7,
        0.7,
        1.0,
        1.0,
        1.0,
    ]
    for call in model.complete.call_args_list[:12]:
        assert len(call.args[0]) == 2  # история очищена, только system + user
        assert call.args[0][-1]["content"] == experiment.QUESTION
    persisted = json.loads((tmp_path / "experiment.json").read_text(encoding="utf-8"))
    assert persisted == result
    assert (tmp_path / "experiment.csv").exists()
    pool.close.assert_awaited_once()
    model.close.assert_awaited_once()
    assert len(await repository.history(next(iter(repository.profiles)))) == 1


async def test_failed_experiment_preserves_only_successful_actual_rows(experiment_setup, tmp_path):
    config, pool, _, model = experiment_setup
    model.complete.side_effect = [Completion("Первый", {}), LLMError("Ошибка сервиса")]
    with pytest.raises(LLMError):
        await experiment.run(config, tmp_path)
    result = json.loads((tmp_path / "experiment.json").read_text(encoding="utf-8"))
    assert result["status"] == "partial" and len(result["runs"]) == 1
    assert result["runs"][0]["answer"] == "Первый"
    assert result["error"] == "Ошибка сервиса"
    pool.close.assert_awaited_once()
    model.close.assert_awaited_once()


def test_report_marks_missing_experiment_without_invented_answers():
    report = render_report(None, None)
    assert "Эксперимент ещё не выполнен" in report
    assert "ЗАПОЛНИТЬ" in report
    assert "Ответ №1" not in report
    assert "эксперимент успешно выполнен" not in report.lower()


def test_report_escapes_model_output_and_records_failed_checks():
    data = {
        "date": "test",
        "status": "partial",
        "model": "test/model",
        "max_tokens": 1200,
        "question": "test",
        "criteria": [],
        "prompt_comparison": [],
        "runs": [
            {
                "number": 1,
                "temperature": 0.3,
                "length": 1,
                "usage": {},
                "format_ok": "нет",
                "observations": "test",
                "answer": "<script>alert('unsafe')</script>",
            }
        ],
    }
    checks = {
        "date": "test",
        "platform": "test",
        "checks": [{"command": "pytest", "exit_code": 1, "output": "failed"}],
    }
    report = render_report(data, checks)
    assert "<script>alert('unsafe')</script>" not in report
    assert "&lt;script&gt;" in report
    assert "pytest: FAIL" in report
