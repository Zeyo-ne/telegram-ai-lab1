# Project guidance

- Лабораторная №1 из docs/labs-guide.md; лабораторные №2 и №3 отдельно.
- Python 3.12, aiogram 3, asyncpg; сохраняйте инфраструктуру шаблона и healthcheck.
- Не выводите .env, токены, пароли, прокси с учётными данными и историю чатов.
- Telegram-обработчики, LLM-клиент, промпты, SQL и управление контекстом разделены.
- Проверки: python -m pytest -q; python -m ruff check .; python -m ruff format --check .
- Реальные Docker-тесты: RUN_INTEGRATION=1 python -m pytest -m integration -v.
- Не подменяйте результаты эксперимента вымышленными; фиксируйте участие AI и пропуски.
