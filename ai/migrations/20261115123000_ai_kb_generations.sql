-- Borrador local posterior a la migración inicial; no desplegar sin revisión.
-- Cada extracción del mismo PDF conserva sus propios pasajes y embeddings.
ALTER TABLE ai.documents ADD COLUMN processing_config_hash text
    CHECK (processing_config_hash IS NULL OR processing_config_hash ~ '^[0-9a-f]{64}$');
ALTER TABLE ai.documents DROP CONSTRAINT documents_source_id_sha256_key;
CREATE UNIQUE INDEX documents_source_pdf_processing_unique
    ON ai.documents (source_id, sha256, coalesce(processing_config_hash, ''));

CREATE TABLE ai.kb_generations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_label text NOT NULL UNIQUE CHECK (btrim(version_label) <> ''),
    config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    sealed_at timestamptz
);

CREATE TABLE ai.kb_generation_documents (
    generation_id uuid NOT NULL REFERENCES ai.kb_generations (id) ON DELETE RESTRICT,
    source_id uuid NOT NULL REFERENCES ai.sources (id) ON DELETE RESTRICT,
    document_id uuid NOT NULL,
    PRIMARY KEY (generation_id, source_id),
    FOREIGN KEY (document_id, source_id)
        REFERENCES ai.documents (id, source_id) ON DELETE RESTRICT
);

CREATE INDEX kb_generation_documents_by_document
    ON ai.kb_generation_documents (document_id);

-- Una sola referencia mutable; las generaciones y sus miembros son históricos.
CREATE TABLE ai.kb_active (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    generation_id uuid NOT NULL REFERENCES ai.kb_generations (id) ON DELETE RESTRICT,
    activated_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION ai.reject_sealed_kb_membership() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE sealed timestamptz;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT sealed_at INTO sealed FROM ai.kb_generations
        WHERE id = OLD.generation_id FOR UPDATE;
    END IF;
    IF sealed IS NOT NULL THEN
        RAISE EXCEPTION 'Sealed knowledge-base generation is immutable';
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT sealed_at INTO sealed FROM ai.kb_generations
        WHERE id = NEW.generation_id FOR UPDATE;
        IF sealed IS NOT NULL THEN
            RAISE EXCEPTION 'Sealed knowledge-base generation is immutable';
        END IF;
    END IF;
    RETURN coalesce(NEW, OLD);
END
$$;

CREATE TRIGGER kb_membership_immutable
BEFORE INSERT OR UPDATE OR DELETE ON ai.kb_generation_documents
FOR EACH ROW EXECUTE FUNCTION ai.reject_sealed_kb_membership();

CREATE FUNCTION ai.reject_sealed_kb_metadata() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.sealed_at IS NOT NULL AND
       (NEW.version_label, NEW.config_hash, NEW.sealed_at)
       IS DISTINCT FROM (OLD.version_label, OLD.config_hash, OLD.sealed_at) THEN
        RAISE EXCEPTION 'Sealed knowledge-base generation is immutable';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER kb_metadata_immutable
BEFORE UPDATE ON ai.kb_generations
FOR EACH ROW EXECUTE FUNCTION ai.reject_sealed_kb_metadata();

CREATE FUNCTION ai.reject_sealed_document_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_document_id uuid;
BEGIN
    v_document_id := coalesce(OLD.id, NEW.id);
    IF EXISTS (
        SELECT 1 FROM ai.kb_generation_documents AS m
        JOIN ai.kb_generations AS g ON g.id = m.generation_id
        WHERE m.document_id = v_document_id AND g.sealed_at IS NOT NULL
    ) AND (
        TG_OP = 'DELETE' OR
        (NEW.source_id, NEW.sha256, NEW.original_url, NEW.filename,
         NEW.storage_path, NEW.version_label, NEW.page_count,
         NEW.extraction_version, NEW.processing_config_hash)
        IS DISTINCT FROM
        (OLD.source_id, OLD.sha256, OLD.original_url, OLD.filename,
         OLD.storage_path, OLD.version_label, OLD.page_count,
         OLD.extraction_version, OLD.processing_config_hash)
    ) THEN
        RAISE EXCEPTION 'Document in sealed knowledge-base generation is immutable';
    END IF;
    RETURN coalesce(NEW, OLD);
END
$$;

CREATE TRIGGER kb_document_immutable
BEFORE UPDATE OR DELETE ON ai.documents
FOR EACH ROW EXECUTE FUNCTION ai.reject_sealed_document_change();

CREATE FUNCTION ai.reject_sealed_chunk_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_document_id uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        v_document_id := NEW.document_id;
    ELSE
        v_document_id := OLD.document_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM ai.kb_generation_documents AS m
        JOIN ai.kb_generations AS g ON g.id = m.generation_id
        WHERE m.document_id = v_document_id
          AND g.sealed_at IS NOT NULL
    ) OR (TG_OP = 'UPDATE' AND EXISTS (
        SELECT 1 FROM ai.kb_generation_documents AS m
        JOIN ai.kb_generations AS g ON g.id = m.generation_id
        WHERE m.document_id = NEW.document_id AND g.sealed_at IS NOT NULL
    )) THEN
        RAISE EXCEPTION 'Chunks in sealed knowledge-base generation are immutable';
    END IF;
    RETURN coalesce(NEW, OLD);
END
$$;

CREATE TRIGGER kb_chunk_immutable
BEFORE INSERT OR UPDATE OR DELETE ON ai.document_chunks
FOR EACH ROW EXECUTE FUNCTION ai.reject_sealed_chunk_change();

CREATE FUNCTION ai.reject_sealed_embedding_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' AND EXISTS (
        SELECT 1 FROM ai.document_chunks AS c
        JOIN ai.kb_generation_documents AS m ON m.document_id = c.document_id
        JOIN ai.kb_generations AS g ON g.id = m.generation_id
        WHERE c.id = OLD.chunk_id AND g.sealed_at IS NOT NULL
          AND g.config_hash = OLD.config_hash
    ) THEN
        RAISE EXCEPTION 'Embedding in sealed knowledge-base generation is immutable';
    END IF;
    IF TG_OP <> 'DELETE' AND EXISTS (
        SELECT 1 FROM ai.document_chunks AS c
        JOIN ai.kb_generation_documents AS m ON m.document_id = c.document_id
        JOIN ai.kb_generations AS g ON g.id = m.generation_id
        WHERE c.id = NEW.chunk_id AND g.sealed_at IS NOT NULL
          AND g.config_hash = NEW.config_hash
    ) THEN
        RAISE EXCEPTION 'Embedding in sealed knowledge-base generation is immutable';
    END IF;
    RETURN coalesce(NEW, OLD);
END
$$;

CREATE TRIGGER kb_embedding_immutable
BEFORE UPDATE OR DELETE ON ai.chunk_embeddings
FOR EACH ROW EXECUTE FUNCTION ai.reject_sealed_embedding_change();

CREATE FUNCTION ai.check_kb_generation(p_generation_id uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_config_hash text;
BEGIN
    SELECT config_hash INTO v_config_hash FROM ai.kb_generations
    WHERE id = p_generation_id FOR UPDATE;
    IF v_config_hash IS NULL THEN
        RAISE EXCEPTION 'Knowledge-base generation does not exist';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM ai.kb_generation_documents
        WHERE generation_id = p_generation_id
    ) THEN
        RAISE EXCEPTION 'Knowledge-base generation is empty';
    END IF;
    -- Bloquea cambios concurrentes al estado de revisión durante la comprobación.
    PERFORM d.id FROM ai.kb_generation_documents AS m
    JOIN ai.documents AS d ON d.id = m.document_id
    JOIN ai.sources AS s ON s.id = m.source_id
    WHERE m.generation_id = p_generation_id FOR SHARE OF d, s;
    IF EXISTS (
        SELECT 1 FROM ai.kb_generation_documents AS m
        JOIN ai.documents AS d ON d.id = m.document_id
        JOIN ai.sources AS s ON s.id = m.source_id
        WHERE m.generation_id = p_generation_id
          AND (d.review_status <> 'reviewed'
               OR s.catalog_status <> 'catalog_verified'
               OR d.processing_config_hash IS DISTINCT FROM v_config_hash)
    ) OR EXISTS (
        SELECT 1 FROM ai.kb_generation_documents AS m
        WHERE m.generation_id = p_generation_id
          AND NOT EXISTS (SELECT 1 FROM ai.document_chunks AS c
                          WHERE c.document_id = m.document_id)
    ) OR EXISTS (
        SELECT 1 FROM ai.kb_generation_documents AS m
        JOIN ai.document_chunks AS c ON c.document_id = m.document_id
        WHERE m.generation_id = p_generation_id
          AND NOT EXISTS (
              SELECT 1 FROM ai.chunk_embeddings AS e
              WHERE e.chunk_id = c.id AND e.config_hash = v_config_hash
          )
    ) THEN
        RAISE EXCEPTION 'Knowledge-base generation contains unreviewed or incomplete evidence';
    END IF;
END
$$;

CREATE FUNCTION ai.seal_kb_generation(p_generation_id uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    LOCK TABLE ai.document_chunks, ai.chunk_embeddings IN SHARE MODE;
    PERFORM ai.check_kb_generation(p_generation_id);
    UPDATE ai.kb_generations SET sealed_at = now()
    WHERE id = p_generation_id AND sealed_at IS NULL;
END
$$;

CREATE FUNCTION ai.enforce_active_kb() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM ai.check_kb_generation(NEW.generation_id);
    IF NOT EXISTS (SELECT 1 FROM ai.kb_generations
                   WHERE id = NEW.generation_id AND sealed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'Knowledge-base generation must be sealed';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER kb_active_validated
BEFORE INSERT OR UPDATE ON ai.kb_active
FOR EACH ROW EXECUTE FUNCTION ai.enforce_active_kb();

CREATE FUNCTION ai.activate_kb_generation(p_generation_id uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM ai.check_kb_generation(p_generation_id);
    IF NOT EXISTS (SELECT 1 FROM ai.kb_generations
                   WHERE id = p_generation_id AND sealed_at IS NOT NULL) THEN
        RAISE EXCEPTION 'Knowledge-base generation must be sealed';
    END IF;
    INSERT INTO ai.kb_active (singleton, generation_id)
    VALUES (true, p_generation_id)
    ON CONFLICT (singleton) DO UPDATE
      SET generation_id = excluded.generation_id, activated_at = now();
END
$$;

ALTER TABLE ai.kb_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.kb_generation_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai.kb_active ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ai.kb_generations, ai.kb_generation_documents, ai.kb_active
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION ai.reject_sealed_kb_membership(),
    ai.reject_sealed_kb_metadata(), ai.reject_sealed_document_change(),
    ai.reject_sealed_chunk_change(), ai.reject_sealed_embedding_change(),
    ai.check_kb_generation(uuid), ai.enforce_active_kb(),
    ai.seal_kb_generation(uuid), ai.activate_kb_generation(uuid)
    FROM PUBLIC, anon, authenticated, service_role;
