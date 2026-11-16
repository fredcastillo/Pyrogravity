-- Borrador para la cadena compartida de supabase/migrations.
-- Requiere 20261114230000_initial_schemas.sql y pgvector en extensions.
-- Supabase CLI controla la transacción y registra la versión; no añadir BEGIN/COMMIT.

DO $$
BEGIN
    IF to_regnamespace('ai') IS NULL THEN
        RAISE EXCEPTION 'El esquema ai debe existir antes de esta migración';
    END IF;
    IF to_regtype('extensions.vector') IS NULL THEN
        RAISE EXCEPTION 'pgvector debe estar habilitado en extensions';
    END IF;
END
$$;

CREATE TABLE ai.sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_key text NOT NULL UNIQUE CHECK (btrim(source_key) <> ''),
    repository text NOT NULL CHECK (btrim(repository) <> ''),
    external_id text NOT NULL CHECK (btrim(external_id) <> ''),
    title text NOT NULL CHECK (btrim(title) <> ''),
    source_type text NOT NULL CHECK (btrim(source_type) <> ''),
    publisher text NOT NULL CHECK (btrim(publisher) <> ''),
    authors text[] NOT NULL CHECK (
        cardinality(authors) > 0 AND array_position(authors, NULL) IS NULL
    ),
    published_at date,
    canonical_url text NOT NULL CHECK (canonical_url ~ '^https://[^[:space:]]+$'),
    doi text CHECK (doi IS NULL OR doi LIKE '10.%/%'),
    catalog_status text NOT NULL DEFAULT 'candidate' CHECK (
        catalog_status IN ('candidate', 'catalog_verified', 'rejected')
    ),
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (repository, external_id),
    CHECK (catalog_status <> 'catalog_verified' OR verified_at IS NOT NULL)
);

CREATE TABLE ai.documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES ai.sources (id) ON DELETE RESTRICT,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    original_url text NOT NULL CHECK (original_url ~ '^https://[^[:space:]]+$'),
    filename text NOT NULL CHECK (btrim(filename) <> ''),
    storage_path text CHECK (storage_path IS NULL OR btrim(storage_path) <> ''),
    version_label text,
    page_count integer NOT NULL CHECK (page_count > 0),
    extraction_version text CHECK (
        extraction_version IS NULL OR btrim(extraction_version) <> ''
    ),
    review_status text NOT NULL DEFAULT 'downloaded' CHECK (
        review_status IN ('downloaded', 'extracted', 'reviewed', 'rejected')
    ),
    retrieved_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz,
    UNIQUE (source_id, sha256),
    UNIQUE (id, source_id),
    CHECK (
        review_status NOT IN ('extracted', 'reviewed')
        OR extraction_version IS NOT NULL
    ),
    CHECK (review_status <> 'reviewed' OR reviewed_at IS NOT NULL)
);

CREATE TABLE ai.document_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES ai.documents (id) ON DELETE RESTRICT,
    page_number integer NOT NULL CHECK (page_number > 0),
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    char_start integer NOT NULL CHECK (char_start >= 0),
    char_end integer NOT NULL CHECK (char_end > char_start),
    content text NOT NULL CHECK (btrim(content) <> ''),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    section_title text,
    content_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english'::regconfig, content)
    ) STORED,
    UNIQUE (document_id, page_number, chunk_index),
    CHECK (char_length(content) = char_end - char_start)
);

CREATE TABLE ai.chunk_embeddings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id uuid NOT NULL REFERENCES ai.document_chunks (id) ON DELETE RESTRICT,
    model_name text NOT NULL CHECK (btrim(model_name) <> ''),
    model_version text,
    config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    dimensions smallint NOT NULL DEFAULT 1024 CHECK (dimensions = 1024),
    embedding extensions.vector(1024) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, config_hash),
    CHECK (extensions.vector_dims(embedding) = dimensions),
    CHECK (extensions.vector_norm(embedding) > 0)
);

CREATE TABLE ai.ingestion_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES ai.sources (id) ON DELETE RESTRICT,
    document_id uuid,
    status text NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed')
    ),
    pipeline_version text NOT NULL CHECK (btrim(pipeline_version) <> ''),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    chunks_created integer NOT NULL DEFAULT 0 CHECK (chunks_created >= 0),
    error_code text CHECK (
        error_code IS NULL OR error_code ~ '^[a-z0-9_]{1,64}$'
    ),
    FOREIGN KEY (document_id, source_id)
        REFERENCES ai.documents (id, source_id) ON DELETE RESTRICT,
    CHECK (status = 'queued' OR started_at IS NOT NULL),
    CHECK (
        (status IN ('succeeded', 'failed')) = (finished_at IS NOT NULL)
    ),
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK ((status = 'failed') = (error_code IS NOT NULL))
);

CREATE INDEX documents_by_source_status
    ON ai.documents (source_id, review_status);
CREATE INDEX document_chunks_fts
    ON ai.document_chunks USING gin (content_tsv);
CREATE INDEX ingestion_jobs_by_source_created
    ON ai.ingestion_jobs (source_id, created_at DESC);

ALTER TABLE ai.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.chunk_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.ingestion_jobs ENABLE ROW LEVEL SECURITY;

-- Esquema privado y cerrado hasta acordar el rol servidor de ingesta/consulta.
REVOKE ALL ON SCHEMA ai FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON ALL TABLES IN SCHEMA ai
    FROM PUBLIC, anon, authenticated, service_role;
