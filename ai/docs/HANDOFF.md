# Handoff de Pyrogravity AI

## Chat global y preguntas amplias · 2026-11-17

- La portada, el Atlas y las fichas abren el mismo chat desde una burbuja o **Consultar fuentes**. El navegador conserva el estudio seleccionado para los seguimientos y presenta orientación del catálogo cuando el visitante empieza con una pregunta amplia.
- `core/engine.py` intenta recuperar documentos revisados cuando una pregunta conceptual menciona una variable numérica y no solicita una medición exacta. Una clasificación desconocida puede recuperar evidencia si la pregunta es del dominio científico o identifica un estudio documentado.
- Las solicitudes de filas o valores exactos conservan los requisitos de evidencia científica. El selector de pasajes sigue validando las premisas antes de devolver citas.
- `tests/test_engine.py` cubre preguntas conceptuales con vocabulario numérico y la abstención ante filas sin datos. Playwright cubre chat global, cambio de contexto, apertura desde el Atlas, errores controlados y las dos vistas de gráficas.

## Consultas por nombre de estudio · 2026-11-16

- `core/document_queries.py` reconoce nombres, códigos PSI y preguntas breves de BASS-II y FLEX. Las variantes con y sin tilde llegan a la misma búsqueda. Si falta el estudio en una pregunta de seguimiento, se pide identificarlo.
- `core/engine.py` y `retrieval/{runtime,postgres}.py` acotan la recuperación textual y vectorial a las fuentes de los estudios reconocidos. El selector sigue recibiendo las premisas completas cuando la pregunta formula una condición específica. Las citas siguen apuntando a pasajes literales.
- La cobertura documental registrada es BASS-II (NTRS 20160000593) y FLEX (NTRS 20130014061). Para añadir estudios a la detección, registra sus alias con su fuente documental revisada y prueba una consulta por título y una abstención. Los cinco análisis por CSV se consultan desde el Atlas.
- Verificación local de contratos y motor disponible en `ai/tests/test_engine.py`. La prueba de PostgreSQL en `ai/tests/test_ingestion_repository.py` cubre el alcance de la búsqueda y requiere la base desechable de CI. La confirmación final depende de la prueba pública del commit que publique AWS.

## Integración AWS · 2026-11-16

Evaluación del parche y Rerank contra la generación activa: 10/10 casos correctos, incluidos 8 positivos con el pasaje esperado y 2 abstenciones. Reporte reproducible en `../evaluations/aws-20261116-engine.json`. Es una muestra acotada; no demuestra exactitud general. Las pruebas de API pública se repiten después del despliegue.

El operador está integrando el PR #48. Runtime, lector de citas, lector científico e ingesta conectan por el Session pooler con identidades distintas; sus valores están separados en Secrets Manager, sin credencial de administración. La invocación backend → AI usa HTTPS autenticado por IAM. La prueba pública verificó cinco valores científicos y una comparación contra PostgreSQL, además de una respuesta documental con citas. Detectó un falso soporte ante una pregunta con una premisa ausente; se endurece la selección por pertinencia completa y se fija temperatura cero. Las pruebas posteriores al despliegue y la evaluación del Rerank deben registrarse antes de declarar aceptación completa. No se han alterado documentos, migraciones ni mediciones.

Actualizado: 2026-11-15. Rama: `users/johan`, mismo clon `Pyrogravity-1`, sin worktrees. El PR #43 está fusionado en `main` (`b08dc65`), incorporado por fast-forward. El usuario autoriza cambios de integración y push, pide commits en español, sin coautoría AI ni reviewers. El despliegue y las pruebas restantes los realizará el equipo por instrucción posterior.

## Objetivo y estado real

Conectar API pública → servicio AI privado → Cohere y Supabase, con los cinco análisis de Stanley y citas verificadas. La conexión pública en AWS todavía no se ha desplegado desde esta sesión. Instrucciones completas: `../../docs/despliegue-ia-integrada.md`.

- Supabase: migraciones compartidas de KB, citas y grupos aplicadas. Se crearon cuatro logins separados para runtime, ingesta, citas y lectura científica. Solo sus secretos locales en `ai/.env` ignorado; no copiar todo ese archivo a los servicios porque también conserva acceso de migración.
- Datos científicos comprobados: 21 datasets, 2.862 registros, 24.252 mediciones. El adaptador PostgreSQL devolvió resultados para los cinco análisis con el lector dedicado: BASS-II 579 datos, FLEX 955, Flame Design 1.113, CFI-G 395, SPICE 3.022 (incluyen derivados, no son cantidades de filas CSV).
- KB activa `40d8e346-5399-458d-854d-5772e4a6ee45`, etiqueta `flex-bass2-20261115-v1`: 2 documentos, 53 fragmentos/vectores; configuración `d8afa5b756e3773fcd8047d5c13efcae6ee8e6f5ff4cfda456cb105745db9eb0`. FLEX fue aprobado anteriormente por Johan. BASS-II tiene revisión técnica automatizada de sus casos, documentada sin atribuir aprobación humana.
- La generación anterior `815aa64a-1f52-4120-bfd9-95a375729e77` sigue sellada y disponible para rollback. No se borró evidencia.

## Cambios preparados

- `llm/cohere_client.py`, `core/engine.py`: JSON mode para selección, validación estricta preservada y texto numérico sin confundir IDs o versiones con mediciones.
- `app/application/scientific_result_resolver.py`, `app/api/ai.py`, settings: nuevo resolver del catálogo PostgreSQL para cinco análisis, IDs/celdas comprobados, scope y hash del subconjunto; la ruta real ya no usa el resolver FLEX local. La clase antigua se conserva para compatibilidad de pruebas existentes.
- Mapper: admite derivados trazables, citas documentales literales con cifras y respuestas ensambladas desde claims validados; conserva preferencia pública de gráfico y controla fallo del lector de citas. JSON público sin cambios.
- `llm/cohere_rerank.py`, `retrieval/runtime.py`, fábrica: reranker opcional sobre pool mayor; requiere `COHERE_RERANK_MODEL` y recuperación híbrida. Desactivado en plantilla hasta medirlo.
- BASS-II ingestado y generación de dos fuentes activada. Casos, ficha y resultados reales en `evaluations/`.
- Dockerfiles, `compose.ai.yml`, gateway TLS, plantillas de secretos e instrucciones de despliegue; `scripts/verify_live_ai.py` entrega comprobaciones públicas con referencia real PostgreSQL. Se excluye `.cache` del contexto Docker.

## Verificación ejecutada y límites

- 14 pruebas focales Cohere/engine aprobadas después de corregir JSON.
- Evaluación real de FLEX: 5/5, cuatro respuestas con evidencia y una abstención.
- API+AI: 138 aprobadas, cero omitidas, con PostgreSQL 17/pgvector 0.8.2 desechable. Se detuvo ese contenedor.
- Dos fuentes, antes de Rerank: 10 casos, 60% correctos, 50% de evidencia esperada en positivos y 100% de abstención en dos negativos. Los cuatro positivos BASS-II seleccionaron pasajes secundarios. Las métricas están publicadas sin ocultar fallos.
- El usuario indicó que el equipo ejecutará las pruebas restantes. Rerank opcional, preferencia de gráfico, control adicional de fallo de citas y empaquetado se terminaron después de la suite: todavía no probados. No se ejecutó `verify_live_ai.py`, no se comprobó el recorrido por HTTPS ni la web desplegada con estos cambios.
- El primer intento de activar la generación BASS usó un nombre de columna incorrecto y falló antes de escribir; se corrigió a `review_status` y se aplicó la activación completa. Un comando de ficha duplicó `ai/` en la ruta; la ficha se regeneró con rutas correctas. No son bloqueos actuales.

## Próximo paso del equipo

1. Revisar e integrar el nuevo PR; construir imágenes y ejecutar las pruebas finales.
2. Medir Rerank con los mismos diez casos y decidir si activarlo. No declarar aceptada la recuperación BASS-II con el resultado actual.
3. Configurar secretos mínimos y certificado HTTPS privado; desplegar backend, IA y frontend sin demo. Aplicar almacenamiento privado de PDF con los ARN reales.
4. Ejecutar `scripts/verify_live_ai.py` y recorridos de navegador, permisos y caída del proveedor. Registrar SHA y resultados.

No se requiere otra aprobación de contratos para utilizar esta conexión. El almacenamiento S3 y el despliegue AWS siguen a cargo del responsable de infraestructura. No hay secretos en los documentos.
