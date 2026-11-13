"""База знань: розбиття статей на шматки, індексація і пошук.

Два режими пошуку:
  * OpenAI-ембединги + косинусна близькість (на Postgres — через pgvector, оператор <=>);
  * BM25 по словах — працює без ключа і без інтернету, для невеликої бази знань його вистачає.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select, text

from .config import settings
from .db import Chunk, Document, Session, engine

CHUNK_SIZE = 600   # символів


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    title: str
    url: str | None
    text: str
    score: float


# ---------- підготовка тексту ----------

def split_into_chunks(content: str, size: int = CHUNK_SIZE) -> list[str]:
    """Ріжемо по абзацах, склеюючи короткі, щоб шматок не розривав думку посередині."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) > size:
            chunks.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        chunks.append(current)
    return chunks


WORD_RE = re.compile(r"[a-zа-щьюяґєії0-9']+", re.IGNORECASE)

# дуже грубий стемінг: відрізаємо типові закінчення, щоб "доставка/доставки/доставку" збігалися
ENDINGS = sorted(["ами", "ями", "ові", "еві", "ого", "ому", "ими", "іми", "ій", "ий", "ая", "ою", "ею", "ої", "их", "ів",
                  "ах", "ях", "ам", "ям", "ом", "ем", "у", "ю", "а", "я", "і", "и", "е", "о", "ь"], key=len, reverse=True)
STOP = {"і", "й", "та", "в", "у", "на", "з", "із", "до", "по", "за", "що", "як", "чи", "а", "не", "це", "я", "ви",
        "вас", "мені", "можна", "є", "для", "від", "про", "мій", "моє", "моя", "мене", "якщо", "так", "скільки"}


# розмовні варіанти, які мають знаходити ту саму статтю
SYNONYMS = {"кот": "кіт", "кішк": "кіт", "кошен": "кіт", "собак": "пес", "цуцен": "пес", "доставлят": "доставк"}


def tokenize(value: str) -> list[str]:
    words = []
    for w in WORD_RE.findall(value.lower().replace("’", "'")):
        if w in STOP:
            continue
        for end in ENDINGS:
            if len(w) - len(end) >= 3 and w.endswith(end):
                w = w[: -len(end)]
                break
        words.append(SYNONYMS.get(w, w))
    return words


# ---------- індексація ----------

def embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.embeddings.create(model=settings.embedding_model, input=texts)
    return [item.embedding for item in resp.data]


def reindex_document(session, doc: Document):
    session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    pieces = split_into_chunks(f"{doc.title}\n\n{doc.content}")
    vectors = embed(pieces) if settings.openai_api_key else [None] * len(pieces)
    session.add_all(Chunk(document_id=doc.id, text=p, embedding=v) for p, v in zip(pieces, vectors))


def load_markdown_folder(folder: Path):
    """Початкове наповнення з папки knowledge_base/*.md (перший рядок '# Заголовок', далі 'url: ...')."""
    with Session() as session:
        for path in sorted(folder.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            title_line, _, rest = raw.partition("\n")
            url = None
            if rest.startswith("url:"):
                url_line, _, rest = rest.partition("\n")
                url = url_line.removeprefix("url:").strip()
            title = title_line.lstrip("# ").strip()

            doc = session.scalar(select(Document).where(Document.title == title))
            if doc:
                doc.content, doc.url = rest.strip(), url
            else:
                doc = Document(title=title, url=url, content=rest.strip())
                session.add(doc)
                session.flush()
            reindex_document(session, doc)
        session.commit()


# ---------- пошук ----------

class BM25:
    def __init__(self, docs: list[list[str]], k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.avg_len = sum(map(len, docs)) / max(len(docs), 1)
        df = Counter(word for doc in docs for word in set(doc))
        n = len(docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.tf = [Counter(doc) for doc in docs]

    def score(self, query: list[str], i: int) -> float:
        total, tf, length = 0.0, self.tf[i], len(self.docs[i])
        for w in query:
            if w not in tf:
                continue
            freq = tf[w]
            total += self.idf[w] * freq * (self.k1 + 1) / (freq + self.k1 * (1 - self.b + self.b * length / self.avg_len))
        return total


def _bm25_search(question: str, chunks, limit: int) -> list[tuple[Chunk, float]]:
    query = tokenize(question)
    if not query or not chunks:
        return []
    bm25 = BM25([tokenize(c.text) for c in chunks])
    scored = [(c, bm25.score(query, i)) for i, c in enumerate(chunks)]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    # Оцінка для порогу — яка частка "ваги" слів запиту знайшлась у фрагменті (0..1).
    # Сирий BM25 залежить від довжини запиту, а так поріг однаковий для будь-якого питання.
    words = set(query)
    total_idf = sum(bm25.idf.get(w, 1.0) for w in words) or 1

    def coverage(chunk_index):
        present = words & bm25.tf[chunk_index].keys()
        return sum(bm25.idf.get(w, 1.0) for w in present) / total_idf

    index = {id(c): i for i, c in enumerate(chunks)}
    return [(c, coverage(index[id(c)])) for c, s in scored[:limit] if s > 0]


def _vector_search(question: str, session, limit: int) -> list[tuple[Chunk, float]]:
    [query_vec] = embed([question])

    if engine.dialect.name == "postgresql":
        rows = session.execute(
            text("SELECT id, 1 - (embedding <=> CAST(:q AS vector)) AS score FROM chunks ORDER BY embedding <=> CAST(:q AS vector) LIMIT :n"),
            {"q": str(query_vec), "n": limit},
        ).all()
        by_id = {c.id: c for c in session.scalars(select(Chunk).where(Chunk.id.in_([r.id for r in rows])))}
        return [(by_id[r.id], float(r.score)) for r in rows]

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)

    chunks = session.scalars(select(Chunk).where(Chunk.embedding.isnot(None))).all()
    scored = sorted(((c, cosine(query_vec, c.embedding)) for c in chunks), key=lambda p: p[1], reverse=True)
    return scored[:limit]


def search(question: str, limit: int = 3) -> list[Hit]:
    with Session() as session:
        if settings.openai_api_key:
            found = _vector_search(question, session, limit)
        else:
            found = _bm25_search(question, session.scalars(select(Chunk)).all(), limit)

        docs = {d.id: d for d in session.scalars(select(Document))}
        return [
            Hit(c.id, c.document_id, docs[c.document_id].title, docs[c.document_id].url, c.text, round(score, 3))
            for c, score in found
        ]
