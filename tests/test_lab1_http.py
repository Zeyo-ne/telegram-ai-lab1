import asyncio
from dataclasses import replace

import pytest
from aiohttp import web

from app.config import Settings
from app.llm import HTTPModel, LLMError


@pytest.fixture
async def endpoint(unused_tcp_port):
    requests = []
    state = {
        "status": 200,
        "body": {
            "choices": [{"message": {"content": "Ответ"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 15},
        },
        "delay": 0,
    }

    async def handler(request):
        requests.append(
            {"body": await request.json(), "auth": request.headers.get("Authorization")}
        )
        if state["delay"]:
            await asyncio.sleep(state["delay"])
        if state.get("raw") is not None:
            return web.Response(text=state["raw"], status=state["status"])
        return web.json_response(state["body"], status=state["status"])

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    config = Settings(
        bot_token="unused",
        postgres_password="unused",
        llm_api_key="secret-key",
        llm_base_url=f"http://127.0.0.1:{unused_tcp_port}/v1",
        llm_model="test-model",
        llm_retries=0,
    )
    try:
        yield config, requests, state
    finally:
        await runner.cleanup()


async def test_http_request_contains_ordered_roles_temperature_and_bearer(endpoint):
    config, requests, _ = endpoint
    model = HTTPModel(config)
    messages = [{"role": "system", "content": "Инструкция"}, {"role": "user", "content": "Вопрос"}]
    try:
        answer = await model.complete(messages, 0.7)
        assert answer.text == "Ответ" and answer.usage == {"total_tokens": 15}
        assert requests == [
            {
                "body": {
                    "model": "test-model",
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 1200,
                    "stream": False,
                },
                "auth": "Bearer secret-key",
            }
        ]
    finally:
        await model.close()
    assert model.session.closed


@pytest.mark.parametrize("status", [400, 401, 402, 403, 429, 500, 503, 302])
async def test_http_error_is_safe_and_body_not_exposed(endpoint, status):
    config, requests, state = endpoint
    state.update(status=status, body={"error": "secret-key sensitive-dialogue"})
    model = HTTPModel(config)
    try:
        with pytest.raises(LLMError) as caught:
            await model.complete([{"role": "user", "content": "private"}], 0.3)
        assert "secret-key" not in str(caught.value)
        assert "sensitive-dialogue" not in str(caught.value)
        assert len(requests) == 1
    finally:
        await model.close()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "   "}}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": "text"}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "text"}, "finish_reason": "content_filter"}]},
        [],
        None,
    ],
)
async def test_malformed_empty_and_truncated_responses_are_errors(endpoint, body):
    config, _, state = endpoint
    state["body"] = body
    model = HTTPModel(config)
    try:
        with pytest.raises(LLMError):
            await model.complete([], 0.3)
    finally:
        await model.close()


async def test_invalid_json_is_safe_error(endpoint):
    config, _, state = endpoint
    state["raw"] = "not-json secret-key"
    model = HTTPModel(config)
    try:
        with pytest.raises(LLMError, match="некорректный"):
            await model.complete([], 0.3)
    finally:
        await model.close()


async def test_timeout_is_bounded_safe_error(endpoint):
    config, _, state = endpoint
    state["delay"] = 0.1
    model = HTTPModel(replace(config, llm_timeout=0.01))
    try:
        with pytest.raises(LLMError, match="не успела"):
            await model.complete([], 0.3)
    finally:
        await model.close()


async def test_retry_limit_is_enforced(endpoint):
    config, requests, state = endpoint
    state["status"] = 503
    model = HTTPModel(replace(config, llm_retries=1))
    try:
        with pytest.raises(LLMError, match="недоступен"):
            await model.complete([], 0.3)
        assert len(requests) == 2
    finally:
        await model.close()


async def test_authorization_error_is_never_retried(endpoint):
    config, requests, state = endpoint
    state["status"] = 401
    model = HTTPModel(replace(config, llm_retries=2))
    try:
        with pytest.raises(LLMError):
            await model.complete([], 0.3)
        assert len(requests) == 1
    finally:
        await model.close()
