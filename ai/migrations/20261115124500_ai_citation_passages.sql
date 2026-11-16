-- Borrador posterior a 20261115120000_ai_initial.sql. No aplicar fuera de la
-- cadena compartida de Supabase ni conceder acceso antes de acordar el rol lector.
CREATE VIEW ai.citation_passages WITH (security_barrier = true) AS
SELECT
    c.id AS passage_id,
    c.document_id,
    d.sha256 AS document_sha256,
    c.page_number,
    c.content_sha256 AS passage_sha256,
    c.content AS passage_text,
    d.extraction_version,
    s.source_key AS source_id,
    s.title AS source_title,
    s.canonical_url AS source_url
FROM ai.document_chunks AS c
JOIN ai.documents AS d ON d.id = c.document_id
JOIN ai.sources AS s ON s.id = d.source_id
JOIN ai.kb_generation_documents AS m ON m.document_id = d.id
JOIN ai.kb_active AS a ON a.generation_id = m.generation_id
JOIN ai.kb_generations AS g ON g.id = a.generation_id
WHERE d.review_status = 'reviewed'
  AND s.catalog_status = 'catalog_verified'
  AND EXISTS (
      SELECT 1 FROM ai.chunk_embeddings AS e
      WHERE e.chunk_id = c.id AND e.config_hash = g.config_hash
  );

REVOKE ALL ON ai.citation_passages FROM PUBLIC, anon, authenticated, service_role;
