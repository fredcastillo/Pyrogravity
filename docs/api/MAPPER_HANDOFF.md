# Backend AI mapper handoff

**Fecha:** 2026-11-15  
**Rama:** `users/gregori`  
**Pull request:** [#35](https://github.com/fredcastillo/Pyrogravity/pull/35)  
**HEAD publicado:** `a68ae86bbc73bc686e19f2a85d3362659da5b894`

## Estado

El mapper público `public-1.1` ↔ contrato interno AI v1.1 está implementado en el backend y publicado en la rama del PR. Valida el request público, resuelve los resultados científicos admitidos, construye `AiQueryRequest` v1.1, llama al cliente interno protegido y valida la respuesta interna antes de generar la respuesta pública.

El proveedor real sigue **desactivado por defecto** (`AI_PROVIDER_ENABLED=false`). No se debe habilitar en despliegue hasta que Michael cierre autenticación entre servicios y el rol lector dedicado para la vista privada de pasajes. Con el proveedor desactivado, las consultas con ensayos seleccionados siguen respondiendo `503 AI_UNAVAILABLE`; sin ensayos, la ruta conserva el comportamiento de respuesta documental o insuficiencia de evidencia.

## Implementación

- `app/application/public_ai_mapper.py`: validación contra JSON Schema v1.1, conversión del request, autorización de referencias científicas/gráficos y validación de citas, cifras y unidades.
- `app/application/scientific_result_resolver.py`: resolución PSI-69 FLEX desde manifiesto y ETL oficial, con comprobación de hashes y admisibilidad de mediciones.
- `app/application/public_ai_orchestrator.py`: orquesta resolución, llamada interna, verificación y mapeo público.
- `app/infrastructure/internal_ai_client.py`: cliente HTTP interno con autenticación bearer y límites de tiempo.
- `app/infrastructure/citation_passage_reader.py`: lectura aislada de pasajes privados para verificar citas.
- `app/api/ai.py` y `app/core/settings.py`: integración detrás del flag de proveedor, apagado por defecto, y validación de configuración/rol lector.

El ejemplo científico PSI-69 FLEX usa filas del dataset real y el manifiesto fijado: ensayos 1 y 2, `burn_time` 4.30 s y 5.00 s. Los puntos del gráfico se generan desde esos resultados backend, no desde la respuesta IA.

## Verificación local

Comandos ejecutados en `C:\flame\backend`:

```powershell
python scripts/export_openapi.py
python -m pytest -q
git diff --check
```

Resultado de la suite: **38 passed, 1 warning**. El warning es una `PendingDeprecationWarning` de Starlette relacionada con `python_multipart`.

## Artefactos públicos

- OpenAPI: `docs/api/openapi.json`
- Ejemplos: `docs/api/examples/`
- Request: `public_ai_request.json`
- Respuesta supported con datos científicos PSI-69: `public_ai_supported.json`
- Insuficiencia de evidencia: `public_ai_insufficient.json`
- Timeout upstream: `504_ai_timeout.json`

## PR y riesgo de integración

Los commits del mapper y sus pruebas ya están en el PR #35:

- `f0814e7` — `feat(api): add gated public AI v1.1 mapper`
- `cc3de66` — `test(api): publish mapper-backed PSI-69 example`
- `a68ae86` — `test(api): cover AI provider gate and timeout`

Al momento de este handoff, el PR #35 contiene además cambios históricos de `ai/` de Johan: **91 archivos `ai/` en el diff contra `origin/main`** (118 archivos cambiados en la comparación web). `origin/main` todavía no incluye #33. Coordinar la reducción de ese diff con la integración de #33 antes de fusionar #35. No se reescribió historial ni se hizo force push.

## Pendientes

- **Michael:** cerrar autenticación entre servicios y aprovisionar/confirmar el rol lector dedicado para `ai.citation_passages`; mantener `AI_PROVIDER_ENABLED=false` hasta completar ambos.
- **Johan:** confirmar el formato final de `data_ref` si el resolvedor real debe sustituir al adaptador demo.
- **Stanley:** revisar que la selección de `ScientificResult` admisible y la fuente científica usada por el resolver coincidan con su integración.
- **Bryant:** revisar tipos públicos y consumir `docs/api/openapi.json`.
- **Integración PR:** después de integrar #33, revisar el diff de #35, retirar del PR los 91 archivos `ai/` fuera de alcance y volver a ejecutar la suite antes de merge.

## Generación de tipos frontend

```bash
npx openapi-typescript docs/api/openapi.json -o src/api/schema.d.ts
```

Contrato público y rutas de request/respuesta: estables para `public-1.1`. El proveedor live, la lectura de pasajes y el resolvedor real `data_ref` siguen condicionados a las dependencias pendientes anteriores.
