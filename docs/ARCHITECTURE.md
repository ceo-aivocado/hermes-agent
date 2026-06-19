# Hermes Bot - Orchestration Architecture

## Назначение

Hermes Bot orchestration - это слой правил, skills, hooks, CI gates и automations вокруг репозитория `ceo-aivocado/hermes-agent`. Цель: MAIN может принимать задачи от АЮ, распределять работу между ролями, держать `ROADMAP.md` актуальным и эскалировать только настоящие блокеры.

## Основные части

| Часть | Где лежит | Что делает |
|---|---|---|
| Durable rules | `AGENTS.md` | Общие правила, роли, escalation triggers, production safety. |
| Status | `ROADMAP.md` | Текущая фаза, задачи, вопросы, блокеры. |
| Skills | `.agents/skills/` | Повторяемые workflows для MAIN, PM, Research, Dev, QA и Telegram escalation. |
| Hooks | `.codex/hooks.json`, `.codex/hooks/` | Блокируют опасные shell/edit операции до выполнения. |
| CI gates | `.github/workflows/label-validator.yml`, `roadmap-consistency.yml` | Проверяют labels и ручные правки `ROADMAP.md` в PR. |
| Mobile docs | `docs/PROMPT_DECK.md`, `docs/MOBILE_WORKFLOW.md` | Помогают АЮ запускать задачи с телефона. |
| Automations | Codex app | Запускают daily brief, roadmap sync fallback и stuck watcher. |

## Роли

- `Hermes Bot MAIN / Orchestrator`: главный маршрутизатор, roadmap owner, PR/merge/deploy coordinator.
- `Hermes Bot Product Manager`: превращает идеи в specs.
- `Hermes Bot Research / Analysis`: готовит research memos.
- `Hermes Bot Developer Core`: меняет critical runtime и core logic.
- `Hermes Bot Developer Edge`: меняет integrations, plugins, Telegram and edge flows.
- `Hermes Bot QA / BugFix`: воспроизводит баги и готовит regression fixes.

## Поток работы

1. АЮ пишет задачу в MAIN chat.
2. MAIN читает `AGENTS.md`, `ROADMAP.md` и выбирает роль.
3. Если задача простая, MAIN делает её сам; если нет - передаёт по hand-off contract.
4. Рабочий агент открывает PR с labels.
5. CI gates проверяют labels, roadmap consistency и обычные тесты.
6. MAIN ждёт approval, merge и обновляет `ROADMAP.md`.

## Эскалации

Skill `hermes-escalate-telegram` отправляет push в Telegram только по пяти trigger-ам:

- Contradiction
- Architectural
- Irreversible
- Stuck-after-retry
- Ambiguity

Routine progress reports не отправляются в Telegram.

## Production

Phase 5 production lock пока пропущен. До его подключения production-действия не автоматизируются. Любой deploy/restart требует отдельного явного prompt-а от АЮ.
