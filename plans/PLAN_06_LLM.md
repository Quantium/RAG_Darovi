# Phase 6: LLM Implementation — Retriever, Client, Generators & Automations

**Goal**: Implement the RAG retrieval layer, the multi-provider LLM client, SQL/Sheets generators, and the automation engine. After this phase, the system can answer questions about ingested documents and extract structured data.

**Depends on**: Phase 5 (embedder and Milvus store operational).

**Success Criteria**: Tests in `test_rag/`, `test_generator/`, and `test_automation/` turn GREEN. A query can be embedded, relevant chunks retrieved from Milvus, and an LLM-generated answer returned with source references.

---

## Step 6.1 — Retriever (Semantic Search)

**File**: `src/rag/retriever.py`

**Class**: `Retriever`

**Constructor** (DI for all dependencies):

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict

import structlog

logger = structlog.get_logger()


@dataclass
class RetrievedChunk:
    text: str
    source_file_id: str
    source_name: str
    section_title: str
    chunk_index: int
    score: float


class Retriever:
    def __init__(
        self,
        embedder: BatchEmbedder,
        vector_store: MilvusStore,
        cache: Any | None = None,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._cache = cache  # Redis client connected to settings.redis_cache_url (DB 2)
        self._cache_ttl = 3600  # 1 hour

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        document_type: str | None = None,
    ) -> list[RetrievedChunk]:
        ...
```

**Logic**:

1. If `query` is empty, return `[]`.
2. Build cache key: `hash(query + str(top_k) + str(document_type))`.
3. Check Redis cache (`self._cache`). If hit, deserialize and return.
4. Embed the query: `embeddings = await self._embedder.embed_texts([query])` → extract `query_vector = embeddings[0]`.
5. Search Milvus: `results = self._vector_store.search(query_vector, top_k, partition=document_type)`.
6. Map results to `RetrievedChunk` objects.
7. Cache serialized results in Redis with TTL.
8. Log: `logger.info("retriever.search", query_length=len(query), results=len(chunks))`.
9. Return sorted by score descending.

**Tests to turn GREEN**: `tests/test_rag/test_retriever.py`

**SC**: `pytest tests/test_rag/test_retriever.py -v` → all pass.

---

## Step 6.2 — LLM Client (Strategy Pattern)

**File**: `src/rag/llm_client.py`

**Protocol**:

```python
from __future__ import annotations

from typing import AsyncIterator, Protocol

import structlog

logger = structlog.get_logger()


class LLMClient(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> str: ...

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]: ...
```

**Single concrete implementation** — all three providers (Ollama, Gemini, DeepSeek) use the same OpenAI-compatible API, so a single class with different constructor args is sufficient (DRY):

```python
import openai


class OpenAICompatibleLLMClient:
    """LLM client for any OpenAI-compatible API (Ollama, Gemini, DeepSeek)."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> str:
        self._check_circuit()
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            self._consecutive_failures = 0
            return response.choices[0].message.content or ""
        except Exception as exc:
            self._record_failure()
            raise

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        self._check_circuit()
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    self._consecutive_failures = 0
                    yield delta
        except Exception as exc:
            self._record_failure()
            raise
```

**Circuit breaker** (inline, no external dependency):

```python
    import time

    def _check_circuit(self) -> None:
        if self._consecutive_failures >= 3 and time.time() < self._circuit_open_until:
            raise ConnectionError(
                f"Circuit breaker open. Retry after {self._circuit_open_until - time.time():.0f}s"
            )

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            self._circuit_open_until = time.time() + 60.0
            logger.warning("llm.circuit_open", failures=self._consecutive_failures, cooldown=60)
```

**Factory**:

```python
def create_llm_client(settings: Settings) -> OpenAICompatibleLLMClient:
    """Build the LLM client from settings. Provider determines base_url and api_key."""
    providers = {
        "ollama": (settings.llm_base_url, "ollama"),
        "gemini": (
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            settings.llm_api_key.get_secret_value(),
        ),
        "deepseek": (
            "https://api.deepseek.com/v1/",
            settings.llm_api_key.get_secret_value(),
        ),
    }
    if settings.llm_provider not in providers:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")

    base_url, api_key = providers[settings.llm_provider]
    logger.info("llm.client_created", provider=settings.llm_provider, model=settings.llm_model)
    return OpenAICompatibleLLMClient(base_url=base_url, api_key=api_key, model=settings.llm_model)
```

> **Backward compatibility**: PLAN_02 tests import `OllamaLLMClient`, `GeminiLLMClient`, `DeepSeekLLMClient`. Add type aliases at the bottom of the file:
> ```python
> OllamaLLMClient = OpenAICompatibleLLMClient
> GeminiLLMClient = OpenAICompatibleLLMClient
> DeepSeekLLMClient = OpenAICompatibleLLMClient
> ```
> This satisfies `isinstance` checks in tests while keeping a single implementation.

**Tests to turn GREEN**: `tests/test_rag/test_llm_client.py`

**SC**: `pytest tests/test_rag/test_llm_client.py -v` → all pass.

---

## Step 6.3 — Conversation Memory

**File**: `src/rag/conversation.py` (new file)

Redis-backed conversation store that enables multi-turn context in RAG queries:

```python
from __future__ import annotations

import json
from dataclasses import dataclass

import redis
import structlog

logger = structlog.get_logger()

MAX_HISTORY_TURNS = 10
CONVERSATION_TTL = 3600  # 1 hour


@dataclass
class ConversationTurn:
    role: str  # "user" or "assistant"
    content: str


class ConversationStore:
    def __init__(self, redis_url: str) -> None:
        self._redis = redis.Redis.from_url(redis_url)

    def get_history(self, conversation_id: str) -> list[ConversationTurn]:
        raw = self._redis.get(f"conv:{conversation_id}")
        if not raw:
            return []
        turns = json.loads(raw)
        return [ConversationTurn(**t) for t in turns]

    def append(self, conversation_id: str, role: str, content: str) -> None:
        history = self.get_history(conversation_id)
        history.append(ConversationTurn(role=role, content=content))
        # Keep only the last N turns to bound context size
        history = history[-MAX_HISTORY_TURNS * 2:]
        self._redis.set(
            f"conv:{conversation_id}",
            json.dumps([{"role": t.role, "content": t.content} for t in history]),
            ex=CONVERSATION_TTL,
        )

    def clear(self, conversation_id: str) -> None:
        self._redis.delete(f"conv:{conversation_id}")
```

---

## Step 6.4 — RAG Chain (Retrieve + Generate)

**File**: `src/rag/chain.py` (new file — gives the function a clear import path)

This module contains the core RAG logic used by both the REST endpoint and the WebSocket endpoint. It now accepts optional conversation history for multi-turn context:

```python
from __future__ import annotations

from typing import AsyncIterator

import structlog
from src.rag.retriever import Retriever, RetrievedChunk
from src.rag.llm_client import LLMClient
from src.rag.conversation import ConversationStore, ConversationTurn

logger = structlog.get_logger()

SYSTEM_PROMPT = (
    "Answer the user's question based on the provided context. "
    "Cite sources using [Source: filename | Section: section] format. "
    "If the context doesn't contain relevant information, say so."
)


def _build_messages(
    query: str,
    chunks: list[RetrievedChunk],
    history: list[ConversationTurn] | None = None,
) -> list[dict[str, str]]:
    context = "\n\n".join(
        f"[Source: {c.source_name} | Section: {c.section_title}]\n{c.text}"
        for c in chunks
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    if history:
        for turn in history:
            messages.append({"role": turn.role, "content": turn.content})
    messages.append(
        {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"}
    )
    return messages


async def rag_answer(
    query: str,
    retriever: Retriever,
    llm: LLMClient,
    top_k: int = 10,
    document_type: str | None = None,
    conversation_store: ConversationStore | None = None,
    conversation_id: str | None = None,
) -> tuple[str, list[RetrievedChunk]]:
    """Retrieve relevant chunks and generate a complete answer."""
    chunks = await retriever.retrieve(query, top_k=top_k, document_type=document_type)
    history = (
        conversation_store.get_history(conversation_id)
        if conversation_store and conversation_id
        else None
    )
    messages = _build_messages(query, chunks, history)
    answer = await llm.chat(messages)

    if conversation_store and conversation_id:
        conversation_store.append(conversation_id, "user", query)
        conversation_store.append(conversation_id, "assistant", answer)

    logger.info("rag.answer", query_length=len(query), chunks=len(chunks))
    return answer, chunks


async def rag_answer_stream(
    query: str,
    retriever: Retriever,
    llm: LLMClient,
    top_k: int = 10,
    document_type: str | None = None,
    conversation_store: ConversationStore | None = None,
    conversation_id: str | None = None,
) -> tuple[AsyncIterator[str], list[RetrievedChunk]]:
    """Retrieve relevant chunks and stream the answer token by token.

    Returns (token_iterator, chunks). Chunks are available immediately;
    iterate the token_iterator to get the streamed answer.
    The caller is responsible for calling conversation_store.append()
    after consuming the full stream.
    """
    chunks = await retriever.retrieve(query, top_k=top_k, document_type=document_type)
    history = (
        conversation_store.get_history(conversation_id)
        if conversation_store and conversation_id
        else None
    )
    messages = _build_messages(query, chunks, history)
    token_stream = llm.chat_stream(messages)
    return token_stream, chunks
```

> **Note**: `rag_answer_stream` returns chunks eagerly (they're needed for the `done` WebSocket message) and the token stream lazily. Phase 7's WebSocket handler iterates the stream, collects the full answer, and appends both user query and assistant answer to the conversation store after the stream ends.

---

## Step 6.5 — SQL Generator

**File**: `src/generator/sql_generator.py`

**Class**: `SQLGenerator`

**Constructor**:

```python
from __future__ import annotations

import re
import structlog

logger = structlog.get_logger()

ALLOWED_SQL_PREFIXES = ("CREATE TABLE", "INSERT INTO", "ALTER TABLE", "CREATE INDEX")
FORBIDDEN_SQL_PATTERNS = re.compile(
    r"\b(DROP|DELETE|TRUNCATE|UPDATE|GRANT|REVOKE|ALTER\s+ROLE|CREATE\s+ROLE)\b",
    re.IGNORECASE,
)


class SQLGenerator:
    def __init__(self, retriever: Retriever, llm: LLMClient) -> None:
        self._retriever = retriever
        self._llm = llm
```

**Methods**:

### `async discover_schema(description: str, top_k: int = 20) -> str`

1. Retrieve sample chunks relevant to the description.
2. Prompt LLM to analyze the chunks and propose `CREATE TABLE` SQL.
3. **Validate output**: Only `CREATE TABLE` and `CREATE INDEX` statements are accepted.
4. Return the SQL DDL string.

**Prompt template**:
```
Analyze these document chunks and propose a SQL table schema that captures the structured data.
Return only valid SQL CREATE TABLE statements. No explanation.
Do NOT include DROP, DELETE, UPDATE, TRUNCATE, or any data-modification statements.
Chunks:
{chunks}
User description: {description}
```

### `async extract_data(chunks: list[RetrievedChunk], schema: str, batch_size: int = 10) -> list[str]`

1. Process chunks in batches of `batch_size`.
2. For each batch, prompt LLM to generate `INSERT INTO` statements matching the schema.
3. **SQL Safety Validation** (applied to every statement before returning):
   - Strip comments and blank lines.
   - Keep only lines starting with one of `ALLOWED_SQL_PREFIXES`.
   - Reject any statement matching `FORBIDDEN_SQL_PATTERNS` (DROP, DELETE, TRUNCATE, UPDATE, GRANT, etc.).
   - Log rejected statements: `logger.warning("sql_gen.rejected_statement", sql=stmt[:100])`.
4. Return list of validated INSERT statements.
5. Log: `logger.info("sql_gen.extracted", total_inserts=len(all_inserts), rejected=rejected_count)`.

### `validate_statement(sql: str) -> bool` (static method)

```python
@staticmethod
def validate_statement(sql: str) -> bool:
    """Return True only if the statement is safe to execute."""
    stripped = sql.strip().upper()
    if FORBIDDEN_SQL_PATTERNS.search(sql):
        return False
    return any(stripped.startswith(prefix) for prefix in ALLOWED_SQL_PREFIXES)
```

> **Defense in depth**: Even with validation, the `DBWriter` (Step 6.6) uses a **restricted database user** that only has `CREATE TABLE` and `INSERT` privileges on a dedicated `generated` schema. See Step 6.6 for details.

> **Note**: Both methods accept chunks as parameters for testability. The caller (API route or CLI) is responsible for retrieving chunks and passing them in. This makes the `SQLGenerator` a pure transformer — it doesn't call the retriever directly, following SRP.

**Tests to turn GREEN**: `tests/test_generator/test_sql_generator.py`

**SC**: `pytest tests/test_generator/test_sql_generator.py -v` → all pass.

---

## Step 6.6 — DB Writer

**File**: `src/generator/db_writer.py`

**Class**: `DBWriter`

**Constructor**:

```python
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = structlog.get_logger()


class DBWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
```

**SQL Safety — Restricted Database User**:

LLM-generated SQL is executed using a **dedicated PostgreSQL user** (`rag_generator`) with minimal privileges:

```sql
-- Run once during setup (added to Phase 1 docker-compose init or a migration script)
CREATE SCHEMA IF NOT EXISTS generated;
CREATE USER rag_generator WITH PASSWORD 'generator_pass';
GRANT USAGE ON SCHEMA generated TO rag_generator;
GRANT CREATE ON SCHEMA generated TO rag_generator;
-- Only INSERT and SELECT on tables within the generated schema
ALTER DEFAULT PRIVILEGES IN SCHEMA generated GRANT INSERT, SELECT ON TABLES TO rag_generator;
```

The `DBWriter` session connects using `rag_generator` credentials and sets `search_path = generated`. This means:
- LLM-generated SQL **cannot** access the `public` schema (where `file_records`, `sync_state` live).
- `DROP`, `DELETE`, `TRUNCATE`, `UPDATE` will fail at the DB level even if they bypass application validation.
- All generated tables live in the `generated` schema, isolated from pipeline metadata.

Add to `Settings`:
```python
database_url_generated: SecretStr = SecretStr(
    "postgresql+asyncpg://rag_generator:generator_pass@localhost:5432/rag_darovi"
)
```

**Methods**:

- `execute(sql: str) -> None`:
  1. Validate via `SQLGenerator.validate_statement(sql)` — reject if forbidden.
  2. Run `await self._session.execute(text(sql))`.
  3. Commit.
  4. On error, rollback and raise.

- `execute_many(statements: list[str]) -> int`:
  1. Validate all statements first — reject the batch if any are forbidden.
  2. Execute all statements in a single transaction.
  3. Return count of successful executions.
  4. On any error, rollback the entire transaction and raise.
  5. Log: `logger.info("db_writer.executed", count=len(statements))`.

**Tests to turn GREEN**: `tests/test_generator/test_db_writer.py`

**SC**: `pytest tests/test_generator/test_db_writer.py -v` → all pass.

---

## Step 6.7 — Sheets Writer

**File**: `src/generator/sheets_writer.py`

**Class**: `SheetsWriter`

**Constructor**:

```python
from __future__ import annotations

import gspread
import structlog

logger = structlog.get_logger()


class SheetsWriter:
    def __init__(self, credentials_path: str) -> None:
        self._gc = gspread.service_account(
            filename=credentials_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
```

**Method**: `write_rows(spreadsheet_id: str, sheet_name: str, rows: list[list[str]]) -> None`

1. Open spreadsheet by ID: `self._gc.open_by_key(spreadsheet_id)`.
2. Try to find worksheet by name: `spreadsheet.worksheet(sheet_name)`.
3. If not found, create it: `spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=26)`.
4. Append rows: `worksheet.append_rows(rows)`.
5. Log: `logger.info("sheets.written", sheet=sheet_name, rows=len(rows))`.

**Tests to turn GREEN**: `tests/test_generator/test_sheets_writer.py`

**SC**: `pytest tests/test_generator/test_sheets_writer.py -v` → all pass.

---

## Step 6.8 — Automation Templates

**File**: `src/automation/templates.py`

**Pydantic models**:

```python
from __future__ import annotations

import fnmatch
from typing import Literal

import yaml
from pydantic import BaseModel


class AutomationFilter(BaseModel):
    mime_type: str | None = None
    name_pattern: str | None = None


class AutomationAction(BaseModel):
    type: Literal["execute_sql", "write_sheet", "notify"]
    target: str


class AutomationConfig(BaseModel):
    name: str
    trigger: Literal["on_new_file", "schedule", "manual"]
    filter: AutomationFilter | None = None
    prompt: str
    action: AutomationAction
```

**Parser**: `parse_automation(yaml_str: str) -> AutomationConfig`
- Loads YAML via `yaml.safe_load()`.
- Validates against `AutomationConfig` Pydantic model.
- Raises `ValueError` if required fields are missing or validation fails.

**Filter matching**: `matches_file(filter: AutomationFilter, file_meta: dict) -> bool`
- If `mime_type` is set, check `file_meta["mimeType"] == filter.mime_type`.
- If `name_pattern` is set, use `fnmatch.fnmatch(file_meta["name"], filter.name_pattern)`.
- Both conditions must pass (AND logic). If neither is set, returns `True`.

**Tests to turn GREEN**: `tests/test_automation/test_templates.py`

**SC**: `pytest tests/test_automation/test_templates.py -v` → all pass.

---

## Step 6.9 — Automation Engine

**File**: `src/automation/engine.py`

**Class**: `AutomationEngine`

**Constructor**:

```python
from __future__ import annotations

import structlog
from src.rag.retriever import Retriever
from src.rag.llm_client import LLMClient
from src.generator.db_writer import DBWriter
from src.generator.sheets_writer import SheetsWriter
from src.automation.templates import AutomationConfig, matches_file

logger = structlog.get_logger()


class AutomationEngine:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        db_writer: DBWriter,
        sheets_writer: SheetsWriter,
        configs: list[AutomationConfig],
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._db_writer = db_writer
        self._sheets_writer = sheets_writer
        self._configs = configs
```

**Method**: `async run(trigger: str, file_meta: dict | None = None) -> None`

1. Filter `self._configs` by `trigger` type.
2. For each matching config:
   a. If `filter` is set and `file_meta` provided, check `matches_file()`. Skip if no match.
   b. Retrieve relevant chunks using the config's `prompt`: `chunks = await self._retriever.retrieve(config.prompt)`.
   c. Build messages with chunks as context + config's `prompt` as the user query.
   d. Call `self._llm.chat(messages)` to get the LLM response.
   e. **Parse the LLM response** based on action type:
      - `execute_sql`: Split response by `;`, filter lines starting with `INSERT`/`CREATE`/`UPDATE`, call `self._db_writer.execute_many(statements)`.
      - `write_sheet`: Parse response as CSV rows, call `self._sheets_writer.write_rows(config.action.target, config.name, rows)`.
      - `notify`: Log the response (`logger.info("automation.notify", name=config.name, result=response[:200])`). Extensible to webhooks.
   f. Log: `logger.info("automation.executed", name=config.name, trigger=trigger)`.

**Tests to turn GREEN**: `tests/test_automation/test_engine.py`

**SC**: `pytest tests/test_automation/test_engine.py -v` → all pass.

---

## Step 6.10 — Integration Verification

Run all tests for this phase:

```bash
pytest tests/test_rag/ tests/test_generator/ tests/test_automation/ -v
```

All should be GREEN.

### Implementation order within this phase

Steps 6.1 and 6.2 are independent and **can be implemented in parallel**. Step 6.3 (Conversation) is independent. Step 6.4 (RAG Chain) depends on 6.1+6.2+6.3. Steps 6.5-6.7 depend on 6.1+6.2. Steps 6.8-6.9 depend on 6.5-6.7.

```
6.1 (Retriever) ───┐
6.2 (LLM Client) ──┼──→ 6.4 (RAG Chain) → 6.5 (SQL Gen) ──┐
6.3 (Conversation) ┘                      6.6 (DB Writer) ──┼─→ 6.9 (Engine)
                                           6.7 (Sheets) ─────┘
                                           6.8 (Templates) ──────→ 6.9 (Engine)
```

### Manual RAG Test

> **Prerequisite**: Docker services running, Ollama model pulled (`docker compose exec ollama ollama pull llama3`).

```python
import asyncio
from config.settings import Settings
from src.vectorizer.embedder import BatchEmbedder
from src.vectorizer.milvus_store import MilvusStore
from src.rag.retriever import Retriever
from src.rag.llm_client import create_llm_client
from src.rag.chain import rag_answer

settings = Settings()
embedder = BatchEmbedder(settings)
store = MilvusStore(settings)
retriever = Retriever(embedder=embedder, vector_store=store)
llm = create_llm_client(settings)

answer, sources = asyncio.run(rag_answer("What was Q3 revenue?", retriever, llm))
print(answer)
for s in sources:
    print(f"  [{s.source_name}] {s.section_title}: {s.text[:80]}...")
```

---

## Output of This Phase

- `src/rag/retriever.py` — `RetrievedChunk` dataclass + `Retriever` with Redis caching and structlog
- `src/rag/llm_client.py` — `LLMClient` protocol + `OpenAICompatibleLLMClient` with circuit breaker + `create_llm_client()` factory + backward-compatible aliases
- `src/rag/conversation.py` — `ConversationStore` with Redis-backed multi-turn history (TTL, max turns)
- `src/rag/chain.py` — `rag_answer()` and `rag_answer_stream()` with optional conversation history support
- `src/generator/sql_generator.py` — `SQLGenerator` with schema discovery + batch data extraction + **SQL statement validation** (whitelist + forbidden pattern rejection)
- `src/generator/db_writer.py` — `DBWriter` with transaction support, using **restricted `rag_generator` DB user** on `generated` schema
- `src/generator/sheets_writer.py` — `SheetsWriter` via gspread (uses `settings.google_sheets_credentials` with `spreadsheets` scope)
- `src/automation/templates.py` — `AutomationConfig` Pydantic models + `parse_automation()` + `matches_file()` using `fnmatch`
- `src/automation/engine.py` — `AutomationEngine` with LLM response parsing per action type
- All `test_rag/`, `test_generator/`, `test_automation/` tests GREEN
