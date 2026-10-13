"""Собирает редактируемый HTML-отчёт только из фактически полученных результатов."""

import html
import json
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from statistics import mean

from app.prompts import MODES

ROOT = Path(__file__).resolve().parents[1]

STYLE = """
body{font:16px/1.65 system-ui,sans-serif;color:#152536;background:#eef2f6;margin:0}
main{max-width:900px;margin:32px auto;background:white;padding:52px;border-radius:16px}
h1{font-size:32px;line-height:1.2}h2{margin-top:32px;color:#154e74}
table{border-collapse:collapse;width:100%;font-size:14px}
td,th{border:1px solid #d5dfe8;padding:10px;text-align:left}
th{background:#eff6fa}pre{white-space:pre-wrap;word-break:break-word;font-size:13px;background:#f4f7fa;padding:16px}
.notice{background:#fff2d4;padding:16px;border-left:4px solid #e7a729}
[contenteditable]{background:#f4f8e8;border-bottom:1px dashed #859645;min-height:24px;padding:4px}
button{padding:12px 18px;border:0;border-radius:8px;background:#154e74;color:white;
cursor:pointer;margin-right:8px}
details{margin:10px 0}summary{cursor:pointer}
@media print{body{background:white}main{margin:0;padding:0;max-width:none}.toolbar{display:none}
[contenteditable]{background:white;border:0}h2{break-after:avoid}tr,pre{break-inside:avoid}}
"""


def esc(value) -> str:
    return html.escape(str(value))


def editable(text: str) -> str:
    return f'<div contenteditable="true">{esc(text)}</div>'


def render_report(experiment: dict | None, checks: dict | None) -> str:
    sections = [
        '<div class="toolbar"><button onclick="window.print()">Печать / сохранить PDF</button>'
        '<button onclick="saveReport()">Скачать с правками</button></div>',
        "<h1>Лабораторная работа №1<br>AI-помощник студента в Telegram</h1>",
        editable("ФИО: ЗАПОЛНИТЬ · Группа: ЗАПОЛНИТЬ · Дата: ЗАПОЛНИТЬ"),
        '<p class="notice">Это основа отчёта. Зелёные поля редактируются кликом. '
        "Отсутствующие эксперименты и ручные проверки не считаются выполненными. "
        "Сначала запусти эксперимент, затем дополни анализ и сохрани PDF. "
        "Повторная генерация отчёта заменяет ручные правки: сохраняй их отдельной кнопкой.</p>",
        "<h2>1. Цель и выбранный сервис</h2>",
        "<p>Реализован текстовый помощник с тремя задачами: объяснение программирования, "
        "перевод и проверка знаний. Ответы генерирует внешний OpenAI-совместимый API. "
        "Telegram и языковая модель используют отдельные соединения.</p>",
        editable("Провайдер: ЗАПОЛНИТЬ. Модель: " + (experiment or {}).get("model", "ЗАПОЛНИТЬ")),
        "<h2>2. Архитектура</h2>",
        "<pre>Telegram → Router → Assistant → PostgreSQL: режим, настройки, история\n"
        "                         ↓\n"
        "              инструкции + история + новый вопрос\n"
        "                         ↓\n"
        "                   HTTPModel → LLM API\n"
        "                         ↓\n"
        "               атомарное сохранение пары → разбивка ответа → Telegram</pre>",
        "<p>Обработчики находятся в app/handlers/assistant.py. Сценарии диалога — "
        "app/assistant.py; SQL — app/storage.py; HTTP — app/llm.py; промпты — app/prompts.py; "
        "ограничение контекста — app/history.py; настройки — app/config.py. "
        "LLM-клиент и хранилище подменяются в тестах через интерфейсы.</p>",
        "<h2>3. Данные и ограничение контекста</h2>",
        "<p>lab1_profiles хранит chat_id, режим и temperature. lab1_turns хранит пару "
        "вопрос–ответ, возрастающий id и время. Разделение пользователей обеспечено chat_id "
        "во всех запросах. Пара записывается одной транзакцией только после успешного "
        "ответа модели. /reset удаляет историю своего чата, сохраняя настройки. "
        "Смена режима обновляет режим и удаляет историю одной транзакцией.</p>",
        "<p>По умолчанию хранится 20 сообщений, то есть 10 полных пар. Перед отправкой "
        "удаляются старейшие пары до выполнения лимита CONTEXT_MAX_UNITS=24000 с резервом "
        "1200 выходных токенов. Оценка: число UTF-8 байтов плюс 16 единиц на сообщение. "
        "Это консервативная эвристика, не точный tokenizer. Инструкция, few-shot-примеры "
        "и новый вопрос сохраняются; если они не помещаются сами по себе, запрос "
        "отклоняется до обращения к модели. Лимит должен быть ниже окна выбранной модели. "
        "После перезапуска используется та же PostgreSQL, память процесса не является "
        "источником сохранённых диалогов.</p>",
        "<h2>4. Системные инструкции</h2>",
    ]
    for name, mode in MODES.items():
        sections.append(f"<h3>/{name}: {esc(mode.title)}</h3><pre>{esc(mode.system)}</pre>")
        for question, answer in mode.examples:
            sections.append(
                f"<pre>Пример входа: {esc(question)}\nПример ответа: {esc(answer)}</pre>"
            )
    sections.append(
        "<p>/study задаёт учебную роль, язык, последовательность ответа и поведение при "
        "неполных данных. /translate ограничивает результат переводом или уточнением; "
        "два few-shot-примера показывают оба случая. /quiz задаёт другой сценарий — "
        "проверку ответа студента вместо немедленного объяснения. Системные сообщения "
        "не сохраняются как пользовательские. Промпт не является механизмом авторизации: "
        "модели не передаются секреты или доступ к операциям.</p>"
    )
    sections.append("<h2>5. Эксперимент с temperature</h2>")
    if experiment:
        sections.append(
            f"<p>Дата: {esc(experiment.get('date'))}. Статус: {esc(experiment.get('status'))}. "
            f"Модель: {esc(experiment.get('model'))}; "
            f"max_tokens: {esc(experiment.get('max_tokens'))}. "
            f"Запрос: {esc(experiment.get('question'))}</p>"
        )
        sections.append(
            "<p>Критерии до эксперимента: "
            + "; ".join(esc(value) for value in experiment.get("criteria", []))
            + ".</p>"
        )
        sections.append(
            "<table><tr><th>№</th><th>temperature</th><th>Длина</th>"
            "<th>Токены</th><th>Формат</th><th>Наблюдения</th></tr>"
        )
        for run in experiment.get("runs", []):
            sections.append(
                f"<tr><td>{esc(run['number'])}</td><td>{esc(run['temperature'])}</td>"
                f"<td>{esc(run['length'])}</td>"
                f"<td>{esc(run['usage'].get('total_tokens', 'нет данных'))}</td>"
                f"<td>{editable(run['format_ok'])}</td><td>{editable(run['observations'])}</td></tr>"
            )
        sections.append("</table>")
        sections.append(
            "<h3>Измеренное сравнение</h3><p>Формат оценивается по нумерации "
            "1–3 в начале строк. Сходство — SequenceMatcher, это метрика текста, "
            "а не правильности ответа.</p>"
        )
        for temperature in (0.0, 0.3, 0.7, 1.0):
            group = [row for row in experiment.get("runs", []) if row["temperature"] == temperature]
            if not group:
                continue
            similarities = [
                SequenceMatcher(None, a["answer"], b["answer"]).ratio()
                for a, b in combinations(group, 2)
            ]
            similarity = f"{mean(similarities):.0%}" if similarities else "нет пары"
            compliant = sum(row["format_ok"] == "да" for row in group)
            sections.append(
                f"<p>temperature={temperature}: {len(group)} ответа, "
                f"средняя длина {mean(row['length'] for row in group):.0f} символов; "
                f"формат соблюдён в {compliant}/{len(group)}; среднее сходство {similarity}.</p>"
            )
        for run in experiment.get("runs", []):
            sections.append(
                f"<details><summary>Ответ №{esc(run['number'])}</summary>"
                f"<pre>{esc(run['answer'])}</pre></details>"
            )
    else:
        sections.append(
            '<p class="notice">Эксперимент ещё не выполнен. Запусти '
            "Эксперимент.command на Маке. Будут сохранены 12 настоящих ответов "
            "и ещё два ответа для сравнения инструкций.</p>"
        )
    sections.append(
        editable(
            "АНАЛИЗ: сравни повторяемость, структуру, длину, соблюдение формата "
            "и точность при четырёх настройках. Обоснуй выбранное значение."
        )
    )
    sections.append("<h2>6. Улучшение инструкции</h2>")
    for comparison in (experiment or {}).get("prompt_comparison", []):
        sections.append(
            f"<h3>{esc(comparison['label'])}</h3><pre>{esc(comparison['prompt'])}</pre>"
            f"<pre>{esc(comparison['answer'])}</pre>"
        )
    sections.append(
        editable(
            "ВЫВОД: сравни реальное выполнение трёх пунктов, понятность и "
            "правильность до и после уточнения роли и формата."
        )
    )
    sections.append(
        "<h2>7. Проверки</h2><p>Автоматические сценарии проверяют роли и порядок "
        "контекста, разделение пользователей, смену режима, /reset, /settings, "
        "лимиты, ошибки, HTTP-параметры и длинные ответы. Локальный HTTP-сервер "
        "возвращает управляемые успешные и ошибочные ответы; настоящий API не "
        "вызывается. Тест с PostgreSQL включается отдельно.</p>"
    )
    if checks:
        sections.append(
            f"<p>Проверено: {esc(checks['date'])}; платформа: {esc(checks['platform'])}.</p>"
        )
        for check in checks["checks"]:
            sections.append(
                f"<h3>{esc(check['command'])}: "
                f"{'PASS' if check['exit_code'] == 0 else 'FAIL'}</h3>"
                f"<pre>{esc(check['output'])}</pre>"
            )
    else:
        sections.append("<p>Результаты проверок отсутствуют. Запусти Проверить.command.</p>")
    sections.append(
        editable(
            "РУЧНАЯ ПРОВЕРКА: покажи три режима на живой модели; два разных "
            "Telegram-пользователя до и после перезапуска; ошибки и длинный ответ. "
            "Запиши только фактически выполненные проверки."
        )
    )
    sections.extend(
        [
            "<h2>8. Ограничения</h2><p>Модель может ошибаться. Эвристика объёма не заменяет "
            "tokenizer модели. Данные БД сохраняются локально, резервное копирование отдельно. "
            "Один токен Telegram должен обслуживаться одним polling-процессом. Ответ сначала "
            "сохраняется в БД, затем отправляется: при отказе Telegram запись может остаться "
            "без доставки. Доступность бесплатных моделей и их лимиты меняются. "
            "Реальные ключи и история не записываются в исходники и логи.</p>",
            "<h2>9. Использование AI</h2><p>Для реализации, тестов и инструкции использован "
            "OpenAI Codex. Код и автоматические сценарии подготовлены AI-ассистентом; "
            "проверки запускаются отдельно, фактические ответы модели не подменяются вымышленными. "
            "Пример исправления: первый вариант параметризованного теста использовал весь "
            "длинный текст как идентификатор сценария. На Windows это привело к ошибке "
            "подготовки теста. Добавлены короткие имена ascii, emoji, markup, newlines; "
            "после исправления четыре сценария успешно прошли проверку.</p>",
            editable(
                "ДОПОЛНИ СВОЁ УЧАСТИЕ: что ты запустил, проверил и понял; пример "
                "исправленного или отклонённого тобой предложения AI."
            ),
            "<h2>10. Сдаваемая версия</h2>",
            editable(
                "Репозиторий: https://github.com/Zeyo-ne/telegram-ai-lab1. "
                "Тег сдаваемой версии: lab1 (создать после проверки)."
            ),
        ]
    )
    script = """
function saveReport(){
const blob=new Blob(['<!doctype html>'+document.documentElement.outerHTML],
{type:'text/html;charset=utf-8'});
const a=document.createElement('a');a.href=URL.createObjectURL(blob);
a.download='lab1-report-edited.html';a.click();URL.revokeObjectURL(a.href);
}
"""
    return (
        '<!doctype html><html lang="ru"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Лабораторная №1 — отчёт</title><style>{STYLE}</style>"
        "<main>" + "\n".join(sections) + f"</main><script>{script}</script></html>"
    )


def main() -> int:
    folder = ROOT / "reports"
    folder.mkdir(exist_ok=True)

    def read(name):
        path = folder / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    (folder / "lab1-report.html").write_text(
        render_report(read("experiment.json"), read("checks.json")), encoding="utf-8"
    )
    print("Отчёт: reports/lab1-report.html. Отредактируй зелёные поля и сохрани PDF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
