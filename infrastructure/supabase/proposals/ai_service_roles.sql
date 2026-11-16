-- Propuesta de permisos. Aplicar en CI desechable después de las tres migraciones AI.
-- Los roles de grupo no tienen credenciales. El despliegue requiere aprobación.
CREATE ROLE pyrogravity_ai_ingest NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE pyrogravity_ai_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE pyrogravity_ai_citation_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT USAGE ON SCHEMA ai TO pyrogravity_ai_ingest, pyrogravity_ai_runtime, pyrogravity_ai_citation_reader;
GRANT USAGE ON SCHEMA extensions TO pyrogravity_ai_ingest, pyrogravity_ai_runtime;

-- La ingesta sólo añade resultados y lee los campos usados al repetir un plan.
GRANT SELECT (id, source_key, repository, external_id, title, source_type, publisher, authors,
              published_at, canonical_url, doi, catalog_status),
      INSERT (source_key, repository, external_id, title, source_type, publisher,
              authors, published_at, canonical_url, doi, catalog_status, verified_at)
ON ai.sources TO pyrogravity_ai_ingest;
GRANT SELECT (id, source_id, sha256, original_url, filename, version_label, page_count,
              extraction_version, review_status, processing_config_hash, storage_path),
      INSERT (source_id, sha256, original_url, filename, version_label, page_count,
              extraction_version, review_status, processing_config_hash, storage_path)
ON ai.documents TO pyrogravity_ai_ingest;
GRANT SELECT (id, document_id, page_number, chunk_index, char_start, char_end, content, content_sha256),
      INSERT (document_id, page_number, chunk_index, char_start, char_end, content, content_sha256)
ON ai.document_chunks TO pyrogravity_ai_ingest;
GRANT SELECT (id, chunk_id, config_hash, model_name, dimensions),
      INSERT (chunk_id, model_name, config_hash, dimensions, embedding)
ON ai.chunk_embeddings TO pyrogravity_ai_ingest;
GRANT SELECT (id, source_id, document_id, status, pipeline_version, started_at, finished_at,
              chunks_created, error_code),
      INSERT (source_id, document_id, status, pipeline_version, started_at, finished_at, chunks_created)
ON ai.ingestion_jobs TO pyrogravity_ai_ingest;
GRANT SELECT (id, version_label, config_hash, sealed_at),
      INSERT (version_label, config_hash)
ON ai.kb_generations TO pyrogravity_ai_ingest;
-- El trigger que protege fragmentos consulta membresía y estado de sellado.
GRANT SELECT (generation_id, document_id) ON ai.kb_generation_documents TO pyrogravity_ai_ingest;

CREATE POLICY ingest_sources_read ON ai.sources FOR SELECT TO pyrogravity_ai_ingest USING (true);
CREATE POLICY ingest_sources_add ON ai.sources FOR INSERT TO pyrogravity_ai_ingest WITH CHECK (true);
CREATE POLICY ingest_documents_read ON ai.documents FOR SELECT TO pyrogravity_ai_ingest USING (true);
CREATE POLICY ingest_documents_add ON ai.documents FOR INSERT TO pyrogravity_ai_ingest
    WITH CHECK (review_status IN ('downloaded', 'extracted') AND reviewed_at IS NULL);
CREATE POLICY ingest_chunks_read ON ai.document_chunks FOR SELECT TO pyrogravity_ai_ingest USING (true);
CREATE POLICY ingest_chunks_add ON ai.document_chunks FOR INSERT TO pyrogravity_ai_ingest WITH CHECK (true);
CREATE POLICY ingest_embeddings_read ON ai.chunk_embeddings FOR SELECT TO pyrogravity_ai_ingest USING (true);
CREATE POLICY ingest_embeddings_add ON ai.chunk_embeddings FOR INSERT TO pyrogravity_ai_ingest WITH CHECK (true);
CREATE POLICY ingest_jobs_read ON ai.ingestion_jobs FOR SELECT TO pyrogravity_ai_ingest USING (true);
CREATE POLICY ingest_jobs_add ON ai.ingestion_jobs FOR INSERT TO pyrogravity_ai_ingest WITH CHECK (true);
CREATE POLICY ingest_generations_read ON ai.kb_generations FOR SELECT TO pyrogravity_ai_ingest USING (true);
CREATE POLICY ingest_generations_add ON ai.kb_generations FOR INSERT TO pyrogravity_ai_ingest
    WITH CHECK (sealed_at IS NULL);
CREATE POLICY ingest_membership_read ON ai.kb_generation_documents FOR SELECT TO pyrogravity_ai_ingest USING (true);

-- En runtime, RLS limita el corpus antes de las consultas textuales o vectoriales.
GRANT SELECT (id, source_key, title, canonical_url, catalog_status) ON ai.sources TO pyrogravity_ai_runtime;
GRANT SELECT (id, source_id, sha256, extraction_version, review_status, processing_config_hash)
    ON ai.documents TO pyrogravity_ai_runtime;
GRANT SELECT (id, document_id, page_number, content_sha256, content, content_tsv)
    ON ai.document_chunks TO pyrogravity_ai_runtime;
GRANT SELECT (chunk_id, config_hash, embedding) ON ai.chunk_embeddings TO pyrogravity_ai_runtime;
GRANT SELECT (generation_id) ON ai.kb_active TO pyrogravity_ai_runtime;
GRANT SELECT (generation_id, source_id, document_id) ON ai.kb_generation_documents TO pyrogravity_ai_runtime;
GRANT SELECT (id, config_hash) ON ai.kb_generations TO pyrogravity_ai_runtime;

CREATE POLICY runtime_active_read ON ai.kb_active FOR SELECT TO pyrogravity_ai_runtime USING (true);
CREATE POLICY runtime_generations_read ON ai.kb_generations FOR SELECT TO pyrogravity_ai_runtime
    USING (id IN (SELECT generation_id FROM ai.kb_active));
CREATE POLICY runtime_membership_read ON ai.kb_generation_documents FOR SELECT TO pyrogravity_ai_runtime
    USING (generation_id IN (SELECT generation_id FROM ai.kb_active));
CREATE POLICY runtime_sources_read ON ai.sources FOR SELECT TO pyrogravity_ai_runtime
    USING (catalog_status = 'catalog_verified' AND id IN (SELECT source_id FROM ai.kb_generation_documents));
CREATE POLICY runtime_documents_read ON ai.documents FOR SELECT TO pyrogravity_ai_runtime
    USING (review_status = 'reviewed'
           AND id IN (SELECT document_id FROM ai.kb_generation_documents)
           AND source_id IN (SELECT id FROM ai.sources));
CREATE POLICY runtime_chunks_read ON ai.document_chunks FOR SELECT TO pyrogravity_ai_runtime
    USING (document_id IN (SELECT id FROM ai.documents));
CREATE POLICY runtime_embeddings_read ON ai.chunk_embeddings FOR SELECT TO pyrogravity_ai_runtime
    USING (chunk_id IN (SELECT id FROM ai.document_chunks)
           AND config_hash IN (SELECT config_hash FROM ai.kb_generations));

-- El backend verifica citas con la vista security_barrier de la migración anterior.
GRANT SELECT ON ai.citation_passages TO pyrogravity_ai_citation_reader;
