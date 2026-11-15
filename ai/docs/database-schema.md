# Propuesta de tablas para el esquema `ai`

**Estado:** la migración `20261115120000_ai_initial.sql` se aplicó en Supabase el 2026-11-15 mediante Supabase CLI y quedó registrada en `supabase_migrations.schema_migrations`. Se verificaron cinco tablas vacías con RLS activo, cero políticas y sin acceso de esquema ni permisos de tabla para `anon`, `authenticated` o `service_role`. La copia compartida está publicada en `users/johan` como `8687f8e` y pendiente de fusión a `main`. La vista de citas propuesta para v1.1 no se desplegó. Cohere `embed-v5.0-fast` devolvió 1024 dimensiones en una prueba real anterior.

## Cinco tablas principales

| Tabla | Campos y restricciones esenciales | Propósito |
| --- | --- | --- |
| `ai.sources` | `id` UUID PK; `source_key` único (`ntrs:20130014061`); `repository`, `external_id` únicos en pareja; `title`, `source_type`, `publisher`, `authors`, `published_at`, `canonical_url`, `doi` nullable, `catalog_status`, `verified_at` | Identidad y validación del registro NASA. DOI ausente queda `NULL`. |
| `ai.documents` | `id` UUID PK; `source_id` FK; `sha256` de 64 hex, único por fuente; `original_url`, `filename`, `storage_path` nullable, `version_label` nullable, `page_count` positivo, `extraction_version`, `review_status`, `retrieved_at`, `reviewed_at` | Cada versión descargada del PDF. `storage_path` referencia un bucket privado o AWS, sin guardar el binario en PostgreSQL. |
| `ai.document_chunks` | `id` UUID PK; `document_id` FK; `page_number` positivo; `chunk_index` no negativo; `char_start`, `char_end` con `char_end > char_start`; `content`, `content_sha256`, `section_title` nullable; único `(document_id, page_number, chunk_index)` | Texto recuperable y ubicación exacta. El chunker actual nunca cruza páginas, por eso se usa `page_number` en vez de rango de páginas. |
| `ai.chunk_embeddings` | `id` UUID PK; `chunk_id` FK; `model_name`, `model_version` nullable, `config_hash`, `dimensions = 1024`, `embedding extensions.vector(1024)`, `created_at`; único `(chunk_id, config_hash)` | Vectores separados del texto para reindexar sin perder los fragmentos. No inventar una versión de modelo si Cohere no la informa. |
| `ai.ingestion_jobs` | `id` UUID PK; `source_id` FK; `document_id` FK nullable; `status`, `started_at`, `finished_at`, `pipeline_version`, `chunks_created`, `error_code` saneado | Historial de intentos, errores y reprocesamiento. `document_id` puede faltar si la descarga falló antes de crear el documento. |

Relación: `sources` → `documents` → `document_chunks` → `chunk_embeddings`. `ingestion_jobs` referencia la fuente y, cuando existe, el documento. Las claves externas deben impedir borrados accidentales en cascada; la reindexación debe ser una operación explícita y transaccional.

Estados propuestos: fuente `candidate/catalog_verified/rejected`; documento `downloaded/extracted/reviewed/rejected`; job `queued/running/succeeded/failed`. Los hashes son hexadecimales SHA-256 de 64 caracteres. `config_hash` identifica modelo, dimensión y parámetros de generación para impedir duplicados ambiguos.

## Búsqueda y estados

- Recuperar solo documentos con `review_status = reviewed` y fuentes con `catalog_status = catalog_verified`. La ingesta automática deja un documento en `extracted` hasta que se revise.
- Preparar búsqueda textual con `tsvector` e índice GIN sobre `document_chunks.content`; combinarla con búsqueda vectorial por coseno. Para el primer corpus pequeño puede usarse búsqueda vectorial exacta; añadir HNSW cuando tamaño y pruebas de recuperación justifiquen el índice.
- Fijar `embed-v5.0-fast` y 1024 dimensiones para la primera indexación. Los documentos se envían como `search_document` y las preguntas como `search_query`. Cambiar dimensión exige una migración o almacenamiento separado, no mezclar vectores incompatibles.
- Guardar un identificador de versión del pipeline de extracción/chunking. Si cambian el PDF, el método de extracción o el modelo de embeddings, reindexar de forma reproducible.

## Acceso y alcance

Mantener `ai` fuera de la Data API pública. No conceder acceso a `anon` ni `authenticated`; habilitar RLS como defensa adicional y definir políticas solo cuando se conozca el rol de servicio. El rol actual usado para diagnóstico tiene `CREATE` en los tres esquemas y **no debe asumirse como el rol final de ejecución**. Coordinar con Michael un rol de IA con permisos mínimos y con Stanley cualquier lectura necesaria de `scientific`.

No crear tablas de respuestas, claims, gráficas ni conversaciones en `ai`: los contratos viven en objetos JSON compartidos y el historial operativo, si se habilita, pertenece a `app`.

## Tablas complementarias posteriores

- `ai.document_investigations`: relación muchos a muchos con identificadores de investigación acordados con Stanley; sin FK a `scientific` hasta acordar el contrato.
- `ai.retrieval_evaluations`: resultados de evaluaciones reproducibles. Comenzar con casos versionados en tests; persistir corridas cuando se necesite comparar modelos.
- `ai.query_traces`: métricas de latencia, costos y errores saneados. Preferir primero la observabilidad del servicio; nunca guardar claves ni prompts sensibles sin política explícita.

**Decisiones antes de ingerir o consultar datos:** ubicación definitiva de los PDFs (bucket privado o AWS), rol de servicio y permisos, contrato de identificadores con Stanley y revisión humana de los estados de validación. La migración aplicada exige `ai` y `extensions.vector` preexistentes, deja RLS activo sin políticas y no concede acceso a roles públicos. El SQL publicado debe fusionarse a `main` antes de que otro miembro ejecute `db push` desde esa rama.

La función local de persistencia ya evita duplicar fragmentos y vectores y rechaza cambios de extracción sobre el mismo PDF. La estructura inicial no permite mantener dos extracciones del mismo SHA-256 ni seleccionar una versión activa de la Knowledge Base; un rollback completo exige una migración versionada posterior. Hasta entonces, el sistema no debe declarar una versión nueva como activa ni reemplazar fragmentos revisados.
