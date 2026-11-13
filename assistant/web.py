import secrets
from collections import Counter
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import core, knowledge
from .config import settings
from .db import Document, Message, Session, Ticket, init_db

BASE = Path(__file__).parent
app = FastAPI(title=f"{settings.shop_name} — AI-асистент")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
security = HTTPBasic()


@app.on_event("startup")
def startup():
    init_db()
    with Session() as session:
        empty = session.scalar(select(func.count(Document.id))) == 0
    if empty:
        knowledge.load_markdown_folder(BASE.parent / "knowledge_base")


# ---------- чат ----------

class ChatIn(BaseModel):
    session_id: str = Field(min_length=6, max_length=64)
    message: str = Field(min_length=1, max_length=1000)


@app.post("/api/chat")
def chat(data: ChatIn):
    reply = core.handle(data.session_id, "web", data.message)
    return {"text": reply.text, "sources": reply.sources, "handoff": reply.handoff, "intent": reply.intent}


@app.get("/")
def widget_demo():
    """Демо-сторінка магазину з віджетом у кутку."""
    return FileResponse(BASE / "static" / "demo.html")


# ---------- Viber ----------

@app.post("/viber/webhook")
async def viber_webhook(request: Request):
    event = await request.json()
    if event.get("event") != "message" or event["message"].get("type") != "text":
        return {"status": 0}

    user_id = event["sender"]["id"]
    reply = core.handle(f"vb-{user_id}", "viber", event["message"]["text"])
    text = reply.text
    if reply.sources and reply.sources[0].get("url"):
        text += f"\n\nДетальніше: {reply.sources[0]['url']}"

    async with httpx.AsyncClient() as client:
        await client.post(
            "https://chatapi.viber.com/pa/send_message",
            headers={"X-Viber-Auth-Token": settings.viber_token},
            json={"receiver": user_id, "type": "text", "text": text, "sender": {"name": settings.shop_name}},
        )
    return {"status": 0}


# ---------- адмінка ----------

def admin_only(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username, settings.admin_user)
            and secrets.compare_digest(credentials.password, settings.admin_password)):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


@app.get("/admin", dependencies=[Depends(admin_only)])
def admin(request: Request, edit: int | None = None):
    with Session() as session:
        docs = session.scalars(select(Document).order_by(Document.title)).all()
        questions = session.scalars(select(Message).where(Message.role == "user").order_by(Message.id.desc()).limit(500)).all()
        bot_msgs = session.scalars(select(Message).where(Message.role == "bot")).all()
        tickets = session.scalars(select(Ticket).where(Ticket.status == "open").order_by(Ticket.id.desc()).limit(20)).all()
        editing = session.get(Document, edit) if edit else None

    intents = Counter(m.intent for m in bot_msgs)
    # частота питань: приводимо до основ слів, щоб "як оплатити" і "як оплатити?" рахувались разом
    groups: dict[str, list[str]] = {}
    for q in questions:
        if q.text.strip().isdigit():   # голий номер замовлення — не питання
            continue
        key = " ".join(sorted(set(knowledge.tokenize(q.text)))[:4]) or q.text.lower()
        groups.setdefault(key, []).append(q.text)
    top_questions = sorted(groups.values(), key=len, reverse=True)[:8]

    return templates.TemplateResponse(request, "admin.html", {
        "docs": docs,
        "editing": editing,
        "tickets": tickets,
        "total": len(questions),
        "intents": intents,
        "top_questions": [(qs[0], len(qs)) for qs in top_questions],
        "mode": "OpenAI + векторний пошук" if settings.openai_api_key else "локальний (BM25, без LLM)",
    })


@app.post("/admin/docs", dependencies=[Depends(admin_only)])
def save_doc(doc_id: int | None = Form(None), title: str = Form(...), url: str = Form(""), content: str = Form(...)):
    with Session() as session:
        doc = session.get(Document, doc_id) if doc_id else Document()
        doc.title, doc.url, doc.content = title.strip(), url.strip() or None, content.strip()
        session.add(doc)
        session.flush()
        knowledge.reindex_document(session, doc)
        session.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/docs/{doc_id}/delete", dependencies=[Depends(admin_only)])
def delete_doc(doc_id: int):
    with Session() as session:
        doc = session.get(Document, doc_id)
        if doc:
            session.delete(doc)
            session.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/tickets/{ticket_id}/close", dependencies=[Depends(admin_only)])
def close_ticket(ticket_id: int):
    with Session() as session:
        ticket = session.get(Ticket, ticket_id)
        if ticket:
            ticket.status = "closed"
            session.commit()
    return RedirectResponse("/admin", status_code=303)
