# Migración inicial del esquema AI

`20261115120000_ai_initial.sql` define las cinco tablas de `ai`. Se copió sin cambios a `supabase/migrations/`, se aplicó en Supabase el 2026-11-15 mediante Supabase CLI y se publicó en `users/johan` como `8687f8e`. El PR #27 que contenía esa copia fue cerrado, sin merge verificado; hace falta un nuevo PR para incorporarla a `main`. La base registró la versión `20261115120000`; la verificación posterior confirmó cinco tablas vacías con RLS, cero políticas y ningún permiso para `anon`, `authenticated` ni `service_role`. **Supabase CLI no aplica migraciones desde este directorio**.

`20261115123000_ai_kb_generations.sql` es un borrador local posterior: conserva variantes de procesamiento del mismo PDF y crea generaciones selladas con un único puntero activo. Activar otra generación revierte la versión visible sin borrar filas. Exige revisión de cada documento y vector de la configuración para cada pasaje. El escritor y el recuperador locales ya usan este esquema; **no está desplegado**.

`20261115124500_ai_citation_passages.sql` depende del versionado y es otro borrador local: expone al backend pasajes revisados **de la generación activa** mediante `passage_id`, `document_id`, `document_sha256`, `page_number`, `passage_sha256`, `passage_text`, `extraction_version`, `source_id`, `source_title` y `source_url`. El backend debe comprobar que `quote` sea una subcadena literal de `passage_text` y que los hashes, documento y página coincidan. La vista usa los permisos de su dueño; no recibe acceso ningún rol de aplicación por esta migración. Antes de conceder `USAGE` sobre `ai` y `SELECT` sobre la vista, el equipo debe acordar un rol servidor dedicado de solo lectura. No conceder acceso a `anon`, `authenticated` ni `service_role`.

Antes de otra ejecución de `db push` desde `main`, incorporar por PR la copia ya aplicada que está en `users/johan`. La migración exige que el esquema `ai`, `extensions.vector` y los roles de Supabase (`anon`, `authenticated`, `service_role`) ya existan. No crea extensiones, objetos en `scientific` o `app`, ni políticas que concedan acceso a usuarios. En PostgreSQL desechable de CI, preparar estos prerequisitos antes de ejecutar toda la cadena de migraciones; instalar pgvector en la imagen por sí solo no crea la extensión SQL ni los roles. La migración inicial ya aplicada y publicada debe permanecer inmutable.

El diseño conserva versiones de PDFs mediante SHA-256, fragmentos de una sola página y embeddings de 1024 dimensiones. La búsqueda textual usa `english` para el corpus NASA inicial. El vector se consulta de forma exacta al principio; HNSW se evaluará cuando haya corpus y medidas de latencia/recall. La columna `storage_path` admite el destino privado de PDFs cuando el equipo lo elija.

## Verificación y siguientes pasos

1. Fusionar el SQL exacto de la migración compartida ya publicada; no aplicarlo de nuevo manualmente.
2. Probar sus restricciones en una base PostgreSQL 17 desechable con pgvector cuando se cambie el SQL. `ai/tests/test_schema_migration.py` requiere `AI_SCHEMA_TEST_DATABASE_URL` apuntando a una base local llamada `pyrogravity_ai_test`; sus cambios se revierten al terminar.
3. Decidir la ubicación persistente de PDFs con el equipo.
4. Definir permisos mínimos para un rol de ingesta y otro de consulta. RLS queda activo sin políticas y los roles Data API no tienen acceso. No usar la conexión `postgres` como credencial de ejecución de la aplicación.

La revisión de chunks y el contrato con `scientific` continúan siendo pasos independientes antes de generar respuestas.

**Validación local anterior del 15 de noviembre de 2026:** el SQL y las restricciones pasaron en una base desechable PostgreSQL 17 con pgvector 0.8.2 (`pgvector/pgvector:0.8.2-pg17`). La prueba revirtió todos sus cambios y el contenedor se detuvo. Después se aplicó la misma migración en Supabase y se verificó mediante consultas de solo lectura.
