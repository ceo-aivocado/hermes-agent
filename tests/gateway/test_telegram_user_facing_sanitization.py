import gateway.run as gateway_run
from gateway.config import Platform


def test_telegram_final_response_hides_internal_search_diagnostics():
    raw = (
        "🔎 ФАКТ-ЧЕК\n\n"
        "Что сейчас недоступно:\n"
        "- ❌ Firecrawl search — кредиты исчерпаны, web_search не работает\n"
        "- ❌ YouTube transcript API — IP заблокирован\n\n"
        "По Moltbook конкретно — звучит как вымысел.\n"
        "Как починим Firecrawl — вернусь к этому."
    )

    sanitized = gateway_run._sanitize_gateway_final_response(Platform.TELEGRAM, raw)

    assert "Firecrawl" not in sanitized
    assert "web_search" not in sanitized
    assert "YouTube transcript API" not in sanitized
    assert "IP заблокирован" not in sanitized
    assert "кредиты исчерпаны" not in sanitized
    assert "Внешняя проверка источников сейчас недоступна" in sanitized
    assert "По Moltbook конкретно" in sanitized
