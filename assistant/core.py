"""Мозок асистента: визначаємо, що хоче клієнт, і готуємо відповідь.

Спершу прості правила (номер замовлення, повернення, "покличте людину") — тут LLM не потрібна
і не повинна вигадувати статуси. Решта питань іде в RAG по базі знань.
"""

import logging
import re
from dataclasses import dataclass, field

from . import knowledge, notify, shop_api
from .config import settings
from .db import Message, Session, Ticket

log = logging.getLogger(__name__)

ORDER_RE = re.compile(r"(?:№|#|номер|замовлення)\s*(\d{4,8})|\b(\d{5})\b", re.IGNORECASE)
RETURN_WORDS = ("поверн", "обмін", "обміня", "не підійш", "брак")
STATUS_WORDS = ("де моє", "статус", "відстежити", "коли приїде", "коли буде", "відправили", "ттн")
OPERATOR_WORDS = ("оператор", "менеджер", "жива людина", "людину", "з людиною")

SYSTEM_PROMPT = """Ти — асистент підтримки інтернет-магазину {shop}.
Відповідай українською, коротко і по суті, лише на основі фрагментів бази знань нижче.
Якщо відповіді у фрагментах немає — так і скажи, нічого не вигадуй.
Наприкінці вкажи номер(и) фрагментів, на які спирався, у форматі [1], [2]."""


@dataclass
class Reply:
    text: str
    intent: str
    sources: list[dict] = field(default_factory=list)
    score: float | None = None
    handoff: bool = False


# що бот чекає від користувача в наступному повідомленні (номер замовлення тощо)
_pending: dict[str, str] = {}


def find_order_number(text: str) -> str | None:
    match = ORDER_RE.search(text)
    return (match.group(1) or match.group(2)) if match else None


def handle_order_status(number: str) -> Reply:
    try:
        order = shop_api.get_order(number)
    except shop_api.ShopApiError:
        return Reply("Не вдалося перевірити замовлення, система магазину не відповідає. Спробуйте за кілька хвилин.", "order_status")
    if not order:
        return Reply(f"Не знайшов замовлення №{number}. Перевірте номер — він є в SMS і листі після оформлення.", "order_status")
    return Reply(shop_api.describe_order(order), "order_status")


def handle_return(number: str, reason: str) -> Reply:
    order = shop_api.get_order(number)
    if not order:
        return Reply(f"Не знайшов замовлення №{number}. Перевірте, будь ласка, номер.", "return")
    try:
        return_id = shop_api.create_return(order, reason)
    except ValueError as e:
        return Reply(f"{e} Передаю ваше питання менеджеру.", "return", handoff=True)
    return Reply(
        f"Заявку на повернення {return_id} створено. Відправте товар Новою поштою на відділення №1 у Києві "
        f"(одержувач ФОП «{settings.shop_name}»), вкажіть номер заявки в описі. Гроші повернемо протягом 3 робочих днів після отримання.",
        "return",
    )


def answer_from_knowledge(question: str) -> Reply:
    hits = knowledge.search(question, limit=3)
    best = hits[0].score if hits else 0.0

    if not hits or best < settings.min_score:
        return Reply(
            "Не хочу вводити вас в оману — точної відповіді в мене немає. Передав питання менеджеру, "
            "він напише вам тут найближчим часом (у робочий час — до 15 хвилин).",
            "handoff", score=best, handoff=True,
        )

    sources = [{"title": h.title, "url": h.url} for h in hits if h.score >= settings.min_score]
    # прибираємо повтори, якщо кілька шматків з однієї статті
    sources = list({s["title"]: s for s in sources}.values())

    if settings.openai_api_key:
        text = _llm_answer(question, hits)
    else:
        text = _extractive_answer(question, hits[0])
    return Reply(text, "faq", sources=sources, score=best)


def _llm_answer(question: str, hits) -> str:
    from openai import OpenAI

    context = "\n\n".join(f"[{i}] {h.title}\n{h.text}" for i, h in enumerate(hits, start=1))
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(shop=settings.shop_name)},
            {"role": "user", "content": f"Фрагменти:\n{context}\n\nПитання клієнта: {question}"},
        ],
    )
    return resp.choices[0].message.content.strip()


def _extractive_answer(question: str, hit) -> str:
    """Без LLM: беремо з найкращого фрагмента речення, які найбільше перетинаються з питанням."""
    query = set(knowledge.tokenize(question))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", hit.text) if len(s.strip()) > 15]
    sentences = [s for s in sentences if s != hit.title]

    ranked = sorted(sentences, key=lambda s: len(query & set(knowledge.tokenize(s))), reverse=True)
    picked = [s for s in ranked[:3] if query & set(knowledge.tokenize(s))] or sentences[:2]
    # повертаємо в тому порядку, як вони йдуть у статті, — так читається природніше
    picked.sort(key=sentences.index)
    return " ".join(s.lstrip("-• ") for s in picked)


def handle(session_id: str, channel: str, text: str) -> Reply:
    text = text.strip()
    lower = text.lower()
    waiting_for = _pending.pop(session_id, None)
    number = find_order_number(text)

    if any(w in lower for w in OPERATOR_WORDS):
        reply = Reply("Добре, кличу менеджера. Він відповість тут же, в цьому чаті.", "handoff", handoff=True)
    elif waiting_for and number:
        kind, reason = waiting_for.split(":", 1)
        reply = handle_return(number, reason) if kind == "return" else handle_order_status(number)
    elif any(w in lower for w in RETURN_WORDS) and ("замовлен" in lower or number or "товар" in lower):
        if number:
            reply = handle_return(number, text)
        else:
            _pending[session_id] = f"return:{text}"
            reply = Reply("Допоможу з поверненням. Напишіть, будь ласка, номер замовлення.", "return")
    elif number or any(w in lower for w in STATUS_WORDS):
        if number:
            reply = handle_order_status(number)
        else:
            _pending[session_id] = "status:"
            reply = Reply("Підкажіть номер замовлення — перевірю, де воно зараз.", "order_status")
    else:
        reply = answer_from_knowledge(text)

    _save(session_id, channel, text, reply)
    return reply


def _save(session_id: str, channel: str, question: str, reply: Reply):
    with Session() as session:
        session.add(Message(session_id=session_id, channel=channel, role="user", text=question))
        session.add(Message(session_id=session_id, channel=channel, role="bot", text=reply.text,
                            intent=reply.intent, score=reply.score, sources=reply.sources))
        if reply.handoff:
            session.add(Ticket(session_id=session_id, channel=channel, question=question))
        session.commit()

    if reply.handoff:
        notify.operators(f"🙋 Потрібен оператор ({channel}, сесія {session_id[:8]}):\n{question}")
