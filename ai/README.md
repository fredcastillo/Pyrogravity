# Pyrogravity AI

The AI package owns document retrieval, model access, evidence validation, and later integration with the scientific query engine. The first development step provides a Cohere Chat v2 adapter. It does not treat generated text as a verified scientific answer.

## Local setup

From `ai/`, create a Python 3.12 virtual environment and install the pinned requirements. On the current Windows workstation, `uv` provides Python 3.12:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
Copy-Item .env.example .env
```

Set `COHERE_API_KEY` in the ignored `.env` file and choose a `COHERE_MODEL` available to that key. The example model is a candidate, not a guarantee of access. Environment variables override `.env` values. Do not commit or paste the key into issues, logs, or chat.

Run unit tests without network access:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Run one live provider request when credentials are configured:

```powershell
.venv\Scripts\python.exe scripts\test_cohere.py
```

The Supabase PostgreSQL project already has pgvector enabled. There is no local PostgreSQL extension installation in this step. The future knowledge base uses the `ai` schema; scientific data stays in `scientific`, and backend operational data stays in `app`.

## Database readiness

Place a rotated, server-side PostgreSQL connection URL in the ignored `.env` file as `AI_DATABASE_URL`. The direct endpoint needs IPv6 (unless the project has the IPv4 add-on); use the Supabase session pooler when running on an IPv4-only network. The probe enforces encrypted transport, disables prepared statements for pooler compatibility, and executes only read-only catalog queries.

```powershell
.venv\Scripts\python.exe scripts\probe_database.py
```

The probe reports existence and schema-level permissions for `scientific`, `ai`, and `app`, plus the installed `vector` extension. It does not create schemas or tables. For stronger TLS identity verification, configure `sslmode=verify-full` and `sslrootcert` in the connection URL using the certificate from Supabase Database settings.
