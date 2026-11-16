# Migraciones del esquema AI

La cadena que ejecuta Supabase CLI está en `supabase/migrations/`. Las copias bajo `ai/migrations/` se usan para desarrollo y pruebas; `20261115120000_ai_initial.sql` conserva los bytes ya aplicados.

| Versión | Contenido | Estado remoto al 2026-11-15 |
| --- | --- | --- |
| `20261115120000` | Cinco tablas de fuentes, PDFs, fragmentos, vectores y jobs | Aplicada |
| `20261115123000` | Configuraciones y generaciones selladas con puntero activo | Aplicada |
| `20261115124500` | Vista privada `ai.citation_passages` para citas de la generación activa | Aplicada |
| `20261115170000` | Tres roles de grupo AI, grants y políticas RLS | Aplicada |

El último SQL reside en `supabase/migrations/` y deriva de la propuesta revisada de infraestructura. Los grupos `pyrogravity_ai_ingest`, `pyrogravity_ai_runtime` y `pyrogravity_ai_citation_reader` son `NOLOGIN`; no contienen contraseñas. El rol de ingesta solo añade y consulta lo necesario para planes idempotentes. El runtime lee evidencia revisada de la generación activa. El lector backend consulta exclusivamente la vista de citas. La revisión de documentos, el sellado y la activación siguen reservados a una identidad de publicación separada.

Las migraciones aplicadas en Supabase aún deben incorporarse a `main` mediante PR. El proyecto remoto tiene el esquema, pero no filas de fuentes, documentos, fragmentos ni embeddings. Antes de ingerir, aprovisionar un login no propietario miembro del grupo de ingesta, un login lector para el servicio y un login lector de citas para backend. Guardar secretos fuera de Git. La propuesta de S3 privado para PDF también requiere despliegue.

`ai/tests/test_schema_migration.py` y `ai/tests/test_ingestion_repository.py` usan una base PostgreSQL 17 desechable llamada `pyrogravity_ai_test` con pgvector en `extensions`, mediante `AI_SCHEMA_TEST_DATABASE_URL`. No apuntar esa variable a Supabase.
