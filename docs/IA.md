# Pyrogravity AI: arquitectura, decisiones y estado

**Actualizado:** 15 de noviembre de 2026. **Responsable:** Johan. El código inicial de AI está en la rama [`users/johan`](https://github.com/fredcastillo/Pyrogravity/tree/users/johan); todavía no forma parte de `main`. Este documento describe implementación comprobada y trabajo pendiente, no promesas de los planes PDF.

## Objetivo y conexión con el equipo

El motor de AI responderá preguntas sobre combustión en microgravedad combinando dos rutas: documentos NASA recuperados por RAG para explicaciones y consultas científicas de Stanley para cifras. Gregori expone el contrato por la API; Bryant presenta respuestas, citas y gráficos. Una cifra debe conservar dataset, fila o ensayo, unidad y estado de interpretación. Si falta evidencia, la respuesta debe decirlo.

```text
Frontend → Backend/API → AI Engine
                         ├─ Scientific Query Engine → scientific (Stanley)
                         └─ RAG documental → ai + pgvector (Johan)
                    → Cohere Command A → validación de evidencia → respuesta
```

El proyecto usa un Supabase compartido con `scientific` para datos científicos, `ai` para documentos y embeddings, y `app` para datos operativos. El navegador no accede directamente a PostgreSQL ni a Cohere.

## Decisiones vigentes

- **Generación:** Cohere Command A, con identificador `command-a-03-2025`. La configuración de ejemplo ya lo incluye. Cohere Embed se usará para vectores; Rerank se evaluará cuando haya consultas etiquetadas.
- **Procedencia:** una publicación NASA y cada PDF descargado son entidades distintas. Se conserva URL oficial, SHA-256 del archivo, página, offsets y hash del fragmento. No se inventan DOI ni mediciones.
- **Recuperación:** combinar búsqueda textual y vectorial. El primer índice vectorial usará embeddings de 1024 dimensiones; se medirá su calidad antes de añadir un índice aproximado.
- **Seguridad:** `ai` permanece fuera de la Data API pública; los secretos se mantienen fuera de Git. El acceso de ejecución necesitará un rol con privilegios mínimos. Los documentos recuperados son datos, no instrucciones.
- **Implementación:** Python 3.12, Cohere, Psycopg, Pydantic, PyMuPDF y Pytest, sin framework adicional de orquestación.

## Avance comprobado

| Área | Estado |
| --- | --- |
| Paquete Python y Cohere Chat | Implementados en `users/johan`; una llamada real a Command A respondió correctamente. |
| Supabase | Diagnóstico de solo lectura implementado. PostgreSQL 17.11 y pgvector 0.8.2 en `extensions` se verificaron el 14 de noviembre. |
| Registro documental | Primera fuente NASA NTRS 20130014061 catalogada con metadatos y hash esperado. |
| Ingesta de PDF | Descarga controlada, verificación SHA-256, extracción por página y fragmentos con offsets/hash. El PDF de 11 páginas produjo 33 fragmentos en la inspección registrada. |
| Pruebas | Última ejecución registrada el 14 de noviembre: 17 pruebas de `ai` y 28 combinadas con `data`, todas aprobadas. No se repitieron para redactar este documento. |

**Todavía no están implementados:** las cinco tablas de `ai`, almacenamiento persistente del PDF, embeddings guardados, retriever híbrido, Rerank, orquestador, validador de citas, contrato con las consultas de Stanley y especificaciones de gráficos. La propuesta de tablas está en [`ai/docs/database-schema.md` de la rama de Johan](https://github.com/fredcastillo/Pyrogravity/blob/users/johan/ai/docs/database-schema.md). No se ha aplicado una migración de AI a Supabase.

## Próximos pasos

1. Revisar los fragmentos extraídos y cerrar el diseño de `ai.sources`, `ai.documents`, `ai.document_chunks`, `ai.chunk_embeddings` y `ai.ingestion_jobs`.
2. Preparar una migración versionada y sus pruebas; acordar almacenamiento privado de PDFs y permisos de ejecución antes de desplegarla.
3. Implementar Cohere Embed, indexación reproducible y recuperación textual/vectorial; evaluar calidad con preguntas y fuentes esperadas.
4. Acordar con Stanley el contrato de consulta científica; combinarlo con RAG y validar citas, cifras y unidades.
5. Integrar el motor con el backend y las especificaciones de gráficos, y pasar pruebas de extremo a extremo.

Para retomar desarrollo en `users/johan`, leer `ai/AGENTS.md`, `ai/docs/HANDOFF.md` y `ai/docs/DECISIONS.md`, y comprobar Git y código antes de asumir que este resumen sigue vigente.
