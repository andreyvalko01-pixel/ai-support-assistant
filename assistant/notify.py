import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)


def operators(text: str):
    """Сповіщення в чат операторів. Без налаштувань — просто в лог."""
    if not (settings.telegram_token and settings.operators_chat_id):
        log.info("[оператору] %s", text)
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage",
            json={"chat_id": settings.operators_chat_id, "text": text},
            timeout=10,
        )
    except httpx.HTTPError as e:
        log.error("Не вдалося сповістити операторів: %s", e)
