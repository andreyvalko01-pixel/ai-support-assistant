-- Для PostgreSQL: увімкнути pgvector і перевести колонку ембедингів на тип vector.
-- Виконати один раз після першого запуску (таблиці створює застосунок).
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE chunks
    ALTER COLUMN embedding TYPE vector(1536) USING embedding::text::vector;

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
