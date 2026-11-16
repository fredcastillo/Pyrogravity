# Integración segura del módulo AI

Estado al 2026-11-15: el PR #40 integró contratos, adaptador científico, frontend, backend y CI en `main`. Las migraciones de generaciones, vista privada y roles de grupo AI se aplicaron a Supabase y están versionadas en la rama `users/johan`, pendientes de PR hacia `main`. El servicio interno no está desplegado y no hay corpus activo ni embeddings en Supabase.

## Secuencia de integración

1. **Contratos:** Gregori trae los archivos v1.1 de `users/johan`, incluidos `AiQueryRequest.schema.json` y su ejemplo anidado. `ScientificResult.schema.json` y su ejemplo independiente ya incluyen `canonicalization_version`. Validar los ejemplos con Pydantic y un validador JSON Schema antes de codificar el mapper.
2. **Datos:** Stanley entrega el uso de `run_scientific_result(analysis_name, source, connection, filters, data_dir)` y los identificadores de ensayo/dato que el backend puede autorizar. El backend debe obtener y validar estos resultados antes de llamar a IA; la IA no consulta `scientific` por su cuenta.
3. **CI:** el PR #40 incorporó las pruebas obligatorias de IA y PostgreSQL con pgvector. Mantener ese gate en el PR de seguimiento y comprobar que no se omitan las pruebas de migración.
4. **Migraciones compartidas:** las versiones `20261115123000`, `20261115124500` y `20261115170000` ya constan en el historial remoto. Incorporar sus archivos al `main` mediante el PR de seguimiento antes de otro `db push`.
5. **Acceso a PostgreSQL:** los grupos `pyrogravity_ai_ingest`, `pyrogravity_ai_runtime` y `pyrogravity_ai_citation_reader` tienen grants y RLS, pero son `NOLOGIN`. Aprovisionar credenciales de ejecución distintas de `postgres`, comprobar sus permisos efectivos y mantener `ai` fuera de la Data API y del navegador.
6. **Servicios:** backend y AI se comunican por HTTPS/TLS en red privada. El backend presenta `Authorization: Bearer` con un secreto exclusivo `AI_INTERNAL_TOKEN` de al menos 32 caracteres; ambos servicios lo reciben por el gestor de secretos del despliegue. Rotación, límites de red, timeouts y logs sin preguntas ni credenciales deben verificarse antes de activar el proveedor. El navegador solo llama a `POST /api/v1/ai/query`.
7. **PDF y corpus:** definir un bucket privado y `storage_path` estable; solo el proceso de ingesta y el servicio AI necesitan lectura. Un revisor humano contrasta el PDF fijado y los cinco casos de evaluación con la fuente antes de marcar el documento `reviewed`. Solo entonces se indexa, sella y activa una generación; se miden texto, vector e híbrido antes de elegir estrategia.

## Criterios de aceptación

- CI ejecuta realmente las pruebas de IA y Data; no las omite si falta el paquete de IA.
- Cada rol puede hacer solo sus operaciones previstas; el lector backend no puede seleccionar tablas base ni escribir.
- `ai.citation_passages` devuelve exclusivamente pasajes revisados de la generación activa y coincide con página, documento y hashes.
- El backend rechaza IDs, citas, cifras, unidades y referencias de gráfico que no estén en el contexto autorizado. Una respuesta sin evidencia produce `insufficient_evidence`; un fallo del servicio usa HTTP y `ErrorEnvelope`.
- La primera consulta extremo a extremo utiliza evidencia real revisada y muestra una cita verificable; no se publica como dato NASA ningún valor de demostración.

Las decisiones de roles, ubicación del PDF y autenticación se coordinan con infraestructura y backend antes de cualquier cambio remoto en Supabase.
