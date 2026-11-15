# Handoff de Pyrogravity AI

**Actualizado:** 2026-11-14
**Objetivo de esta sesión:** publicar el primer avance en `users/johan` mediante commits separados de ingesta y documentación, y entregar el siguiente roadmap. El usuario autorizó este commit y push, sin atribución al agente.

## Estado real

- Un solo clon, rama local `users/johan`. El primer push se completó el 2026-11-14: `origin/users/johan` avanzó de `e27c68e` a `a22a353`, que coincide con `HEAD` tras el push. Incluye los commits `2e99666`, `ad68bf1`, `ead4d05`, `5e08677` y `a22a353`; no hubo merges ni cambios remotos de base de datos.
- Ya funcionan el paquete Python 3.12, Cohere Chat, el diagnóstico de Supabase y el registro de la fuente NASA NTRS 20130014061. Esta sesión añadió descarga con hash fijado, extracción por página, normalización de ligaduras, chunks con página/offsets/hash y `scripts/inspect_source.py`.
- El commit `5e08677` incluye `.gitignore`, `pyproject.toml`, manifiesto NASA, `schemas/source.py`, `docs/source-registry.md`, `scripts/inspect_source.py`, el paquete `ingestion/` y `tests/test_ingestion.py`. El commit `a22a353` registró `AGENTS.md`, `README.md`, `docs/HANDOFF.md`, `docs/DECISIONS.md` y `docs/database-schema.md`. Todo está dentro de `ai/`.
- `data/` contiene ETL y tests de Stanley. En este checkout no existen todavía `backend/`, `frontend/` ni `shared/`. El CI y CODEOWNERS del equipo aún buscan `rag/`; el usuario coordina su cambio a `ai/`.

## Verificaciones ejecutadas

- `python -m pytest tests -q` desde `ai/`: **17 pasaron**. `python -m pytest data/tests ai/tests -q` desde la raíz: **28 pasaron**. `compileall` y `uv pip check` pasaron; PyMuPDF 2.1 quedó fijado en `pyproject.toml`.
- `scripts/inspect_source.py --page 5`: PDF NASA de 11 páginas, texto en las 11, 33 chunks, SHA-256 `1488bbb461f2ea0f97c2c2fab6ac0a01603a6837509ab6ac6d1ef02bbf72050b`. No se indexó ni se envió a Cohere.
- Cohere Command respondió `OK` en una llamada real; Cohere Embed `embed-v5.0-fast` devolvió 1024 dimensiones en una llamada real. Estas pruebas comprueban acceso, no calidad científica.
- Supabase respondió con `scientific`, `ai` y `app`; una lectura reciente confirmó PostgreSQL 17.11, `vector` 0.8.2 habilitado en `extensions` y cero tablas en `ai`. Una lectura anterior del mismo día había encontrado `vector` disponible pero sin instalar; este agente no lo activó.
- El `fetch` y el primer push autenticados con la cuenta GitHub del usuario terminaron correctamente. Tras ese push, `HEAD` y `origin/users/johan` coincidían en `a22a353`, con árbol limpio y rama 0 commits delante/0 detrás. No se usó force push ni se añadió al agente como autor o coautor.

## Pendientes y decisiones humanas

- La propuesta de cinco tablas está en `docs/database-schema.md`. Revisar ubicación persistente de PDFs (bucket privado o AWS), rol de ejecución con permisos mínimos, identificadores de Stanley y estados de revisión antes de preparar/aplicar SQL. No crear tablas por ahora.
- La extracción conserva páginas y offsets, pero el paper repite encabezados y contiene tablas; revisar manualmente fragmentos antes de marcarlos `reviewed`. Todavía no hay embeddings almacenados, retriever, respuesta con citas, orquestador ni integración con Stanley/Gregori.
- El usuario autorizó explícitamente los commits y el primer push de este avance. Para cambios futuros rige la aprobación previa. Los commits usan tipo y alcance (`feat(ai)`, `docs(ai)`, etc.), sin atribución al agente.
- Antes del push se revisaron diff, pruebas y ausencia de los valores locales de secretos en lo publicado. El CI del equipo aún no detecta `ai/`; el usuario coordina su ajuste.

## Próxima tarea recomendada

Revisar con Johan `docs/database-schema.md` y chunks de `scripts/inspect_source.py --page 5`. Después preparar la migración SQL revisable para las cinco tablas, sin ejecutarla, e implementar Cohere Embed con `search_document`/`search_query` y comprobación de dimensión. Confirmar con Michael que CI incluya `ai/` antes del PR.
