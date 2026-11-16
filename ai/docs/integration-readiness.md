# Integración segura del módulo AI

Estado al 2026-11-15: el contrato interno v1.1 está publicado en `users/johan` (PR #33). El adaptador científico está en el PR #32 y el contrato público en `users/gregori`. El servicio interno existe, pero no está desplegado; las migraciones de generaciones y de la vista privada siguen solo en `ai/migrations/`. No hay corpus activo ni embeddings en Supabase.

## Secuencia de integración

1. **Contratos:** Gregori trae los archivos v1.1 de `users/johan`, incluidos `AiQueryRequest.schema.json` y su ejemplo anidado. `ScientificResult.schema.json` y su ejemplo independiente ya incluyen `canonicalization_version`. Validar los ejemplos con Pydantic y un validador JSON Schema antes de codificar el mapper.
2. **Datos:** Stanley entrega el uso de `run_scientific_result(analysis_name, source, connection, filters, data_dir)` y los identificadores de ensayo/dato que el backend puede autorizar. El backend debe obtener y validar estos resultados antes de llamar a IA; la IA no consulta `scientific` por su cuenta.
3. **CI:** detectar `ai/`, instalar `ai/requirements.txt`, ejecutar `ai/tests` y las pruebas de Data que importan `pyrogravity_ai` como dependencia obligatoria. La base desechable debe crear `extensions`, instalar `vector` en ese esquema y disponer de los roles de Supabase requeridos por la migración inicial. Ejecutar la cadena completa en orden.
4. **Migraciones compartidas:** integrar la migración inicial ya aplicada `20261115120000_ai_initial.sql` sin cambiar sus bytes. Revisar y copiar después `20261115123000_ai_kb_generations.sql` y `20261115124500_ai_citation_passages.sql` a `supabase/migrations/`; probarlas en una base desechable antes de `db push`. No ejecutar el servicio actualizado contra el esquema inicial sin generaciones.
5. **Acceso a PostgreSQL:** crear credenciales de ejecución distintas de `postgres`. Se requieren tres capacidades: escritor de ingesta (DML específico y políticas RLS), lector AI (SELECT de fuentes, documentos, pasajes, embeddings y generaciones activas) y lector backend (solo `USAGE` en `ai` y `SELECT` de `ai.citation_passages`). Un `GRANT` por sí solo no atraviesa RLS: las políticas deben probarse con cada rol. No conceder `CREATE`, `BYPASSRLS`, propiedad de tablas ni acceso a `anon`, `authenticated` o `service_role`; no exponer `ai` en la Data API ni en el navegador.
6. **Servicios:** backend y AI se comunican por HTTPS/TLS en red privada. El backend presenta `Authorization: Bearer` con un secreto exclusivo `AI_INTERNAL_TOKEN` de al menos 32 caracteres; ambos servicios lo reciben por el gestor de secretos del despliegue. Rotación, límites de red, timeouts y logs sin preguntas ni credenciales deben verificarse antes de activar el proveedor. El navegador solo llama a `POST /api/v1/ai/query`.
7. **PDF y corpus:** definir un bucket privado y `storage_path` estable; solo el proceso de ingesta y el servicio AI necesitan lectura. Un revisor humano contrasta el PDF fijado y los cinco casos de evaluación con la fuente antes de marcar el documento `reviewed`. Solo entonces se indexa, sella y activa una generación; se miden texto, vector e híbrido antes de elegir estrategia.

## Criterios de aceptación

- CI ejecuta realmente las pruebas de IA y Data; no las omite si falta el paquete de IA.
- Cada rol puede hacer solo sus operaciones previstas; el lector backend no puede seleccionar tablas base ni escribir.
- `ai.citation_passages` devuelve exclusivamente pasajes revisados de la generación activa y coincide con página, documento y hashes.
- El backend rechaza IDs, citas, cifras, unidades y referencias de gráfico que no estén en el contexto autorizado. Una respuesta sin evidencia produce `insufficient_evidence`; un fallo del servicio usa HTTP y `ErrorEnvelope`.
- La primera consulta extremo a extremo utiliza evidencia real revisada y muestra una cita verificable; no se publica como dato NASA ningún valor de demostración.

Las decisiones de roles, ubicación del PDF y autenticación se coordinan con infraestructura y backend antes de cualquier cambio remoto en Supabase.
