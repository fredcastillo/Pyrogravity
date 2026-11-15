# Diagnóstico del contrato IA actual

## app/domain/ai_contract.py

En la rama remota actual, AiQueryRequest contiene query_type (exact_value, concept, comparison, summary, mixed), question, experiment_ids, variables, want_chart y language. AiResponse contiene id, status (ok, fallback, insufficient_evidence, rejected), answer, claims, chart, limitations, confidence, model, data_version, corpus_version, degraded_source y created_at. Evidence.value es Decimal y created_at usa UTC. No incluye schema_version.

Este cambio añade schema_version fijo 1.0 mediante la constante única CONTRACT_VERSION. No cambia los estados ni la semántica de los modelos existentes de Johan.

## Diferencias con el contrato de Johan v1.0

- Los estados actuales no coinciden con supported, partially_supported, insufficient_evidence, invalid_request y upstream_unavailable.
- id actual es un texto arbitrario, no request_id UUID.
- claims existe; Claim tiene statement, kind, evidence y citations.
- Evidence requiere experiment_id, variable, metric, dataset_id, dataset_version, trial_id y source_id; el manifiesto PSI-69 no aporta todos esos identificadores.
- No existen visualizations ni metrics; AiResponse usa chart con otra forma.
- limitations existe.
- schema_version queda fijado en 1.0.

Los ejemplos supported y partially_supported no pueden validarse contra el modelo actual. No los transformé ni cambié los estados de Johan. La respuesta supported de FLEX test 1 tampoco puede construirse sin inventar los campos de Evidence que faltan.

## Rutas actuales

- GET /health
- POST /api/v1/ai/query
- POST /api/v1/ai/analyses/summary
- POST /api/v1/ai/analyses/comparison
- POST /api/v1/analyses/summary
- POST /api/v1/analyses/comparison
- GET /api/v1/analyses
- GET /api/v1/analyses/{analysis_id}

El cambio añade GET /api/v1/ai/{request_id}/charts/{chart_id} para el gráfico demo PSI-69. No existen rutas /experiments ni /sources. No hay Parquet de PSI-69 en el árbol actual; el gráfico lee el CSV fuente y normaliza LF a los finales CRLF de origen para comprobar que el contenido coincide con el SHA-256 de data/source_manifest.csv. El resolvedor general basado en data_ref queda TODO(PENDIENTE: Johan).
