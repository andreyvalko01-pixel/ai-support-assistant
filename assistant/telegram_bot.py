"""Telegram-канал асистента (aiogram 3). Запуск: python -m assistant.telegram_bot"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import core
from .config import settings
from .db import init_db

dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        f"Вітаю! Я асистент магазину {settings.shop_name}. Підкажу про доставку, оплату, повернення "
        "і перевірю статус замовлення — просто напишіть питання або номер замовлення."
    )


@dp.message(F.text)
async def on_text(message: Message):
    await message.bot.send_chat_action(message.chat.id, "typing")
    # core.handle синхронний (ходить у БД і, можливо, в OpenAI) — не блокуємо event loop
    reply = await asyncio.to_thread(core.handle, f"tg-{message.chat.id}", "telegram", message.text)

    keyboard = None
    links = [s for s in reply.sources if s.get("url")]
    if links:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📄 {s['title']}", url=s["url"])] for s in links[:2]
        ])
    await message.answer(reply.text, reply_markup=keyboard)


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(settings.telegram_token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
