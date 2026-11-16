# Handoff de Pyrogravity AI

**Actualizado:** 2026-11-15
**Objetivo de esta sesión:** preparar y probar la ingesta idempotente y las primeras rutas de recuperación, mientras el equipo revisa contratos y acceso.

## Estado comprobado

- Un solo clon, rama `users/johan`. La migración inicial de `ai` se aplicó previamente a Supabase y se publicó en el [PR borrador #27](https://github.com/fredcastillo/Pyrogravity/pull/27). Sus cinco tablas están vacías. La vista `ai.citation_passages` sigue como borrador versionado y no está desplegada.
- El usuario autorizó un checkpoint tras pasar las pruebas. Se prepararon cinco commits separados en español: `5e7ecb6` (contratos borrador), `9b4306b` (extracción), `ad3d1ef` (Embed y plan), `0cbf758` (persistencia y recuperación) y `08171cc` (evaluación). `origin/users/johan` no tenía commits nuevos al hacer `fetch`; el push se verifica al cerrar el checkpoint. No hubo merge ni cambios remotos de base de datos. El usuario coordina CI; editar solo `ai/`.
- Cohere Chat, diagnóstico de Supabase, registro de NTRS 20130014061, descarga fijada por SHA-256 y chunking por página ya existían. Ahora hay preparación, persistencia y recuperación local probadas; todavía no hay filas/embeddings en Supabase, servicio AI, orquestador ni integración con Stanley/Gregori/Bryant.

## Cambios de esta sesión

- `pyproject.toml`, `.env.example`, `src/pyrogravity_ai/config.py`: `pypdf` 7.0.0 y `fonttools` 4.68.0 sustituyen PyMuPDF; se configuraron modelo y tamaño de lote de Embed.
- `src/pyrogravity_ai/ingestion/loader.py`, `scripts/inspect_source.py`, `docs/extraction-quality.md`, `tests/test_ingestion.py`: extracción versionada `pypdf-7.0.0-header-v1`, eliminación de primeras líneas idénticas repetidas y prueba de offsets relativos al texto limpio. El PDF fijado sigue dando 11 páginas con texto y 33 fragmentos, sin caracteres de reemplazo. Las fórmulas y tablas requieren cotejo visual; no se marcó el documento `reviewed`.
- `src/pyrogravity_ai/llm/cohere_embed.py`, `tests/test_cohere_embed.py`: adaptador Embed v2 para documentos (`search_document`) y consultas (`search_query`), lotes de hasta 96 y verificación de 1024 valores finitos y norma no nula por vector. Los errores de proveedor se clasifican sin exponer secretos. No hay embeddings persistidos.
- `README.md`, `docs/DECISIONS.md`, `migrations/README.md`, `tests/test_schema_migration.py`: instrucciones y referencias de extracción actualizadas; se documentaron los prerequisitos completos del CI. El SQL inicial publicado no se modificó.
- `ingestion/plan.py`, `scripts/prepare_ingestion.py`, `tests/test_ingestion_plan.py`: plan determinista que comprueba PDF, offsets, hashes y embeddings; expone `config_hash` y `plan_hash`. El comando usa Cohere y no escribe en PostgreSQL.
- `database/ingestion_repository.py`, `tests/test_ingestion_repository.py`: escritura transaccional de las cinco tablas con rol no privilegiado, reintentos sin duplicados y rechazo de reextracción incompatible. Los documentos quedan `extracted`; no existe comando de escritura remota.
- `retrieval/postgres.py`, `tests/test_retrieval.py`: búsqueda textual, coseno exacto y combinación de rankings como candidato. Todas excluyen documentos no revisados; el vector se limita a un `config_hash`. D-013 y D-014 registran las decisiones.
- `retrieval/evaluation.py`, `evaluations/ntrs_20130014061_candidates.json`, `tests/test_retrieval_evaluation.py`: cinco preguntas candidatas con hashes de pasajes, incluidas dos en español y una sin evidencia esperada. Sus extractos literales se comprobaron contra el PDF local; las métricas se bloquean hasta la revisión humana de los casos.

## Verificaciones ejecutadas

- `ai/.venv/Scripts/python.exe ai/scripts/export_contracts.py --check`: terminó correctamente. `uv pip check --python ai/.venv/Scripts/python.exe`: dependencias compatibles. `git diff --check`: sin errores.
- `ai/.venv/Scripts/python.exe ai/scripts/inspect_source.py --page 5`: SHA-256 `1488bbb461f2ea0f97c2c2fab6ac0a01603a6837509ab6ac6d1ef02bbf72050b`, 11 páginas, 33 fragmentos, versión nueva. Una llamada real a Cohere Embed con `embed_query` devolvió un vector de 1024 dimensiones y norma no nula; no se mostró ni guardó la clave. No se hicieron escrituras remotas.
- `ai/.venv/Scripts/python.exe ai/scripts/prepare_ingestion.py`: llamada real a Cohere Embed para 33 fragmentos, todos de 1024 dimensiones; `config_hash` `d8afa5b756e3773fcd8047d5c13efcae6ee8e6f5ff4cfda456cb105745db9eb0` y `plan_hash` `14953dd1e12f2881a80027460ff1bb1de2a0c33e23c6924a91401b39d6e2f9eb`. Sin escrituras remotas.
- Suite completa con PostgreSQL 17 + pgvector 0.8.2 en contenedor desechable: **69 aprobadas**, incluidas migración, RLS, reintento idempotente y recuperación. Los cambios de prueba se revirtieron y el contenedor se detuvo. Sin base local: **67 aprobadas, 2 omitidas** (las dos requieren PostgreSQL desechable).

## Informe externo y pendientes

- **CI bloqueado:** el job de PostgreSQL del PR #27 usa una imagen sin pgvector; además, en una base limpia hay que crear `extensions`, instalar la extensión SQL `vector` en ese esquema y crear los roles de Supabase antes de aplicar las migraciones. El workflow local sigue buscando `rag/` y CODEOWNERS no cubre `ai/`. Michael debe preparar esos prerequisitos en el entorno desechable de CI y ejecutar `ai/tests`; no conviene reescribir el SQL ya aplicado y publicado para adaptar el CI.
- **Contratos aún en revisión:** el informe detectó que v1.1 limita las comparaciones a cinco ensayos y excluye consultas científicas por cohorte, que falta definir la respuesta pública hidratada para Bryant y que `ChartSpec` perdió restricciones de ejes/unidades. La opción C de routing se registró en D-012; faltan mapear las categorías de intención, ajustar la vista de citas y acordar la serialización del adaptador de Stanley. Se publican como borradores con esos bloqueos visibles; no se cambió el modelo v1.1 para darlos por resueltos.
- **Acceso de ejecución:** decidir con Michael roles mínimos para ingesta y lectura de citas, ubicación privada de PDFs, autenticación de `/internal/v1/ai/query` y secretos de despliegue. No usar `postgres` ni claves en navegador. La migración de vista no se despliega hasta acordar lector y contrato.
- **Calidad documental:** revisar manualmente fórmulas/tablas y procedencia antes de marcar el PDF `reviewed`; cualquier reindexación debe conservar versión de extracción, modelo y hashes. Revisar las cinco claves de respuesta candidatas y medir texto/vector/híbrido antes de elegir ranking final o umbral de abstención.
- **Versiones de Knowledge Base:** el esquema inicial solo admite una extracción por `(source_id, PDF SHA-256)`; aún falta una migración para conservar varias extracciones, activar una generación y revertirla sin perder fragmentos. El repositorio actual rechaza reemplazos silenciosos.

## Próxima tarea

Diseñar y probar la migración de generaciones/activación de Knowledge Base antes de una ingesta permanente; preparar casos de evaluación con pasajes revisados y preguntas en inglés y español para medir texto, vector e híbrido. Después, agregar Rerank solo si mejora las métricas, y continuar con orquestación, validación y servicio interno cuando cierren los contratos y roles.
