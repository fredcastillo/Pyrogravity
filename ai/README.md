# Pyrogravity AI

The AI package owns document retrieval, model access, evidence validation, and later integration with the scientific query engine. Cohere Chat and Embed adapters are available; generated text is not treated as a verified scientific answer.

## Local setup

From `ai/`, create a Python 3.12 virtual environment and install the pinned requirements. On the current Windows workstation, `uv` provides Python 3.12:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
Copy-Item .env.example .env
```

Set `COHERE_API_KEY` in the ignored `.env` file and choose a `COHERE_MODEL` available to that key. The example model is a candidate, not a guarantee of access. Environment variables override `.env` values. Do not commit or paste the key into issues, logs, or chat.

`COHERE_EMBED_MODEL` defaults to `embed-v5.0-fast`; document chunks use `search_document` and queries use `search_query`. The adapter checks that each returned vector has 1024 finite, nonzero values. The repository can persist them through an injected connection; no runtime ingestion command is deployed.

Run unit tests without network access:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Run one live provider request when credentials are configured:

```powershell
.venv\Scripts\python.exe scripts\test_cohere.py
```

The Supabase PostgreSQL project has pgvector enabled in `extensions` as confirmed by the live probe on 2026-11-14. There is no local PostgreSQL extension installation. The knowledge base belongs in `ai`; scientific data stays in `scientific`, and backend operational data stays in `app`.

## Database readiness

Place a rotated, server-side PostgreSQL connection URL in the ignored `.env` file as `AI_DATABASE_URL`. The direct endpoint needs IPv6 (unless the project has the IPv4 add-on); use the Supabase session pooler when running on an IPv4-only network. The probe enforces encrypted transport, disables prepared statements for pooler compatibility, and executes only read-only catalog queries.

```powershell
.venv\Scripts\python.exe scripts\probe_database.py
```

The probe reports existence and schema-level permissions for `scientific`, `ai`, and `app`, plus the installed `vector` extension. It does not create schemas or tables. For stronger TLS identity verification, configure `sslmode=verify-full` and `sslrootcert` in the connection URL using the certificate from Supabase Database settings.

## Scientific sources

The [source registry design](docs/source-registry.md) defines catalog, PDF artifact, chunk and citation provenance. The first curated NASA NTRS record is in `sources/ntrs_20130014061.json`; its DOI and declared version are left null because the publisher's catalog does not list either.

The [database schema](docs/database-schema.md) describes five private `ai` tables for provenance, chunks, embeddings and ingestion runs. The initial migration was applied to Supabase on 2026-11-15; the tables remain empty according to the last remote check. Generations and the citation view are local proposals and are not deployed.

The draft [scientific canonicalization rule](docs/scientific-canonical-v1.md) fixes cross-store `data_version`, stable dataset IDs and aggregate input hashes for `ScientificResult v1.1`. Its synthetic examples are in `contracts/v1_1/`; Stanley's adapter and real Parquet/PostgreSQL parity remain pending.

## Inspect the first PDF

The source manifest pins the SHA-256 of the NASA PDF. The script downloads it into ignored `.cache/` if absent, rejects changed bytes, extracts text with `pypdf` and original 1-based page numbers, normalizes typographic ligatures, removes only repeated first-line headers, and creates page-bounded chunks. It does not send the document to Cohere or write to Supabase.

```powershell
.venv\Scripts\python.exe scripts\inspect_source.py
.venv\Scripts\python.exe scripts\inspect_source.py --page 5
```

Review the reported page count, text quality and sample chunks before using the document for retrieval. [Extraction quality notes](docs/extraction-quality.md) record the current review limits. PDF text extraction may need a document-specific adjustment for columns, tables or scanned pages.

## Prepare an ingestion plan

After configuring Cohere, prepare the pinned document and its embeddings without writing to PostgreSQL:

```powershell
.venv\Scripts\python.exe scripts\prepare_ingestion.py
```

The command prints the document hash, extraction version, fragment count, embedding dimensions and deterministic configuration/plan hashes. These hashes identify the input and settings for later idempotent persistence. A changed PDF, chunking strategy or embedding model produces a different plan; existing reviewed documents must never be silently overwritten. Preparation does not mark the document `reviewed` or create database rows.

`pyrogravity_ai.database.ingestion_repository.persist_ingestion()` can store a prepared plan transactionally in the five initial `ai` tables. It requires an injected connection using a dedicated, non-owner ingestion role with explicit RLS policies; it rejects a PostgreSQL administrator or table owner. A repeat run leaves chunks and embeddings unchanged and records another job. With the **published but undeployed generations migration**, another processing configuration of the same PDF gets a separate document row. No ingestion command has been run against Supabase, and the private runtime role has not yet been provisioned. The updated writer must not run against the remote schema until that migration is applied.

`scripts/ingest_source.py` is the guarded writer entry point. A plain run prepares and prints the exact plan without database access. A write requires both `--apply` and `--expect-plan-hash <hash-from-dry-run>`, plus a dedicated `AI_INGEST_DATABASE_URL` in the ignored `.env`. It enforces TLS and the repository rejects privileged roles. Do not use `--apply` against Supabase until the generation migration, writer role and RLS policies are reviewed and deployed.

## Retrieve reviewed evidence

`pyrogravity_ai.retrieval.postgres` provides English full-text search, exact cosine vector search for an explicit `config_hash`, and reciprocal-rank fusion of the two lists. Each query filters to `reviewed` documents from `catalog_verified` sources **in the active Knowledge Base generation** and returns document and passage hashes plus page number. The module accepts an injected PostgreSQL connection; it does not expose a public route or generate answers. The first NASA document is still `extracted`, so it must not appear in production retrieval until manual review. Fusion is an evaluation candidate, not the chosen ranking strategy; Spanish questions, expected passages, recall and abstention thresholds still need a reviewed test set.

Five draft cases are in `evaluations/ntrs_20130014061_candidates.json`. Their expected excerpts and hashes match the current extraction, but their scientific relevance needs human review. `retrieval.evaluation` refuses to report hit rate, mean reciprocal rank or abstention accuracy while any case is still marked `candidate`.
Once the answer keys are reviewed, `compare_retrievers()` can score several strategies on the same cases and report each case's first expected rank, returned count and abstention. It has no hard-coded quality threshold and does not mark candidate cases as approved.

Build or verify the [human review packet](evaluations/ntrs_20130014061_review.md) from the pinned PDF:

```powershell
.venv\Scripts\python.exe scripts\build_evaluation_review.py --check
```

The packet lists each question, expected page, passage hash and a short excerpt. A reviewer must compare it with the original PDF and record which keys are acceptable; generating the packet never changes `review_status`. Once the document and cases are reviewed, the active generation contains this exact source/version, and a dedicated read-only AI role is configured, run:

```powershell
.venv\Scripts\python.exe scripts\evaluate_retrieval.py --cases evaluations\ntrs_20130014061_candidates.json --config-hash <active-config-sha256>
```

The runner reads the active private generation, embeds each question once with Cohere and compares text, vector and RRF at the same `k`. It returns only metrics and case IDs, ranks and counts. Other documents' passages count as distractors. It stops before external access while any case is still `candidate`; it does not write to PostgreSQL or approve evidence.

## Internal AI service

The [integration readiness guide](docs/integration-readiness.md) lists the manual CI, database-role, migration, service-authentication, and private-PDF steps required before enabling the real provider.

The service endpoint is `POST /internal/v1/ai/query` with the versioned `AiQueryRequest` and `AiResponse` contracts. It requires an `Authorization: Bearer` token of at least 32 characters configured as `AI_INTERNAL_TOKEN`. Start it from `ai/` with:

```powershell
.venv\Scripts\uvicorn.exe pyrogravity_ai.service.app:create_app --factory --host 127.0.0.1 --port 8010
```

The server needs `COHERE_API_KEY`, `COHERE_MODEL` and a dedicated read-only `AI_DATABASE_URL`. It defaults to reviewed text retrieval; `AI_RETRIEVAL_STRATEGY=hybrid` additionally requires `AI_EMBED_CONFIG_HASH` for the active generation. Do not point the current code at Supabase until the local Knowledge Base generation migration, RLS policies and reader role are deployed. Keep the service behind private TLS and authenticate the backend to it; the browser must only call the backend.

The orchestrator routes clear questions by rules and asks Cohere for ambiguous intent. Cohere selects evidence IDs from bounded candidates; the final claim text is assembled from validated scientific values or literal reviewed passages. Unknown IDs, malformed model output, altered passage hashes and unauthorized chart references fail closed. Numeric context comes only from the backend's `ScientificResult` objects. The backend still has to verify every returned datum and citation against its authorized source and hydrate charts from scientific data. HTTP errors use `ErrorEnvelope`; `insufficient_evidence` is a successful HTTP 200 with no claims.
