import os
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.sqlite").replace("\\", "/")
os.environ["OPENAI_API_KEY"] = ""

import pytest

from assistant import core, knowledge
from assistant.db import init_db

KB = Path(__file__).parent.parent / "knowledge_base"


@pytest.fixture(scope="module", autouse=True)
def kb():
    init_db()
    knowledge.load_markdown_folder(KB)


def test_split_into_chunks_keeps_paragraphs():
    text = "Перший абзац.\n\nДругий абзац.\n\n" + "Довгий " * 120
    chunks = knowledge.split_into_chunks(text, size=200)
    assert chunks[0].startswith("Перший абзац.")
    assert all(len(c) < 900 for c in chunks)


def test_tokenize_stems_endings():
    assert knowledge.tokenize("доставка") == knowledge.tokenize("доставки") == knowledge.tokenize("доставку")


@pytest.mark.parametrize("question, title", [
    ("Скільки коштує доставка?", "Доставка"),
    ("можна оплатити частинами?", "Оплата"),
    ("як перевести кота на новий корм", "Як підібрати корм"),
    ("до котрої працює підтримка", "Контакти та графік"),
])
def test_search_finds_right_article(question, title):
    hits = knowledge.search(question)
    assert hits and hits[0].title == title


def test_faq_answer_has_source():
    reply = core.handle("s-faq", "web", "Скільки коштує доставка по Києву?")
    assert reply.intent == "faq"
    assert "99 грн" in reply.text
    assert reply.sources[0]["title"] == "Доставка"


def test_unknown_question_goes_to_operator():
    reply = core.handle("s-unknown", "web", "Чи продаєте ви акваріуми для морських риб на 500 літрів?")
    assert reply.handoff


def test_order_status_by_number():
    reply = core.handle("s-order", "web", "Де моє замовлення №10452?")
    assert reply.intent == "order_status"
    assert "20450012345678" in reply.text


def test_order_status_asks_number_first():
    first = core.handle("s-ask", "telegram", "Коли приїде моє замовлення?")
    assert "номер" in first.text.lower()
    second = core.handle("s-ask", "telegram", "10477")
    assert "зібране" in second.text


def test_return_flow():
    first = core.handle("s-ret", "web", "Хочу повернути товар із замовлення")
    assert first.intent == "return"
    second = core.handle("s-ret", "web", "10398")
    assert "R-10398" in second.text


def test_return_too_late_is_handed_off():
    reply = core.handle("s-late", "web", "Повернення замовлення 10211")
    assert reply.handoff


def test_operator_request():
    assert core.handle("s-op", "viber", "Покличте оператора").handoff
