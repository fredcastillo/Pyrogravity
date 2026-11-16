# Entrega de la conexión AI · 2026-11-15

Código preparado en `users/johan`, a partir de `main` con PR #43 integrado. El despliegue lo realizará el equipo. La configuración nueva y el reranker opcional requieren las pruebas de aceptación siguientes; no se afirma que la web pública ya use este código.

## Qué conecta

`frontend → POST /api/v1/ai/query → backend → HTTPS privado → POST /internal/v1/ai/query`.
El backend lee los cinco análisis mediante `run_scientific_result(source="postgres")` de Stanley y un lector dedicado de `scientific`. Limita cada resultado a los ensayos y variables pedidos, conserva advertencias y recalcula `data_version`. No ejecuta ETL por request. La IA recupera únicamente pasajes revisados de la generación activa en `ai`; Cohere selecciona IDs en modo JSON. El backend verifica datos, citas y puntos antes de responder `public-1.1`. El navegador solo conoce la API pública.

Disponibles: BASS-II (`PSI-25`), FLEX (`PSI-69`), Flame Design (`PSI-10`), CFI-G (`PSI-159`) y SPICE (`PSI-107`). Los IDs son `PSI:table_name:source_record`, con el nombre oficial del manifiesto. No se promete acceso a variables o ensayos excluidos por el adaptador. Los agregados sin referencias de ensayo no se envían como si fueran mediciones individuales.

## Supabase ya preparado

- Las migraciones de generaciones, citas y roles están aplicadas; no hay que volver a ejecutar su SQL manualmente.
- Se comprobaron 21 datasets, 2.862 registros y 24.252 mediciones científicas.
- Generación activa: `40d8e346-5399-458d-854d-5772e4a6ee45`, etiqueta `flex-bass2-20261115-v1`: 2 PDF, 53 pasajes y 53 embeddings.
- PDF: NTRS 20130014061 (FLEX, 33 pasajes) y 20160000593 (BASS-II, 20 pasajes). La segunda revisión es técnica automatizada autorizada por Johan, no aprobación humana del equipo. Su alcance y hashes constan en `ai/evaluations/`.
- Logins separados creados: `pyrogravity_scientific_login`, `pyrogravity_ai_runtime_login`, `pyrogravity_ai_ingest_login` y `pyrogravity_ai_citation_login`. Los secretos locales están en el archivo ignorado `ai/.env`; deben entregarse por el gestor de secretos del despliegue.

## Configuración que debe recibir cada servicio

Copiar las plantillas sin publicar sus valores:

| Servicio | Plantilla y secretos necesarios |
|---|---|
| IA | `ai/.env.runtime.example`: Cohere, DSN del runtime, token interno, modelos y configuración de embeddings. No entregar DSN de administrador ni de ingesta. |
| Backend | `.env.backend-runtime.example`: DSN del lector científico, DSN del lector de citas y el mismo token interno. |
| Ingesta/operación | DSN de ingesta y acceso privado al archivo PDF; fuera de los contenedores públicos. |

`AI_CITATION_VIEW_DATABASE_URL` del backend corresponde al secreto local `AI_CITATION_DATABASE_URL`. `PYROGRAVITY_DATABASE_URL` usa el lector científico, no `postgres`. `AI_DATABASE_URL` usa el runtime. Configurar `AI_PROVIDER_ENABLED=true`, `DEMO_MODE=false`, `AI_INTERNAL_URL=https://<servicio-privado>` y un origen CORS explícito. No colocar estos secretos en variables `VITE_*`.

## Imágenes y conexión HTTPS

La imagen raíz ahora incluye el paquete AI y sus JSON Schema; el backend los necesita para consumir el adaptador de Stanley. `ai/Dockerfile` construye el servicio separado sin CSV, PDF, caché ni credenciales.

```sh
docker build -t pyrogravity-api .
docker build -f ai/Dockerfile -t pyrogravity-ai .
```

Para un host Docker, `compose.ai.yml` amplía la configuración existente: web sin demo, backend real, IA sin puerto público y un gateway TLS en una red interna. Copiar `.env.connection.example` a `.env.connection` y completar rutas a los dos archivos privados y al directorio de certificados.

El certificado debe cubrir `ai-gateway`, con `server.crt`, `server.key` y `ca-bundle.pem` que incluya las CA públicas y la CA del servicio privado. El usuario del contenedor Nginx debe poder leer la clave montada; limitar el acceso al operador y al UID del servicio. Los certificados temporales de `ai/.cache/tls` son exclusivamente locales y expiran; no utilizarlos en producción. Para AWS se puede sustituir el gateway por un balanceador HTTPS privado con certificado confiable. Mantener validación TLS; no usar `verify=False`.

```sh
docker compose --env-file .env.connection -f docker-compose.yml -f compose.ai.yml up --build -d
```

Esta orden debe ejecutarla el responsable del despliegue. El nuevo resolver requiere incluir `data/source_manifest.csv` en la imagen, como ya hace el Dockerfile. No precisa CSV ni Parquet para responder desde PostgreSQL.

## Archivo privado de PDF

El servicio responde con texto de Supabase y no necesita descargar PDF por request. El archivo original debe mantenerse en almacenamiento privado para reproducir ingestas. La plantilla existente `infrastructure/aws/proposals/ai-private-pdfs.yaml` crea S3 privado y versionado con permisos de lectura/escritura separados. El desplegador debe aplicarla con los ARN reales y cargar los PDF fijados por SHA-256; usar el hash como clave de objeto y conservar su versión. No copiar `ai/.cache` a una imagen ni publicar el bucket. El archivo S3 aún no está aprovisionado desde esta sesión.

## Pruebas pendientes del equipo

El usuario pidió detener las pruebas adicionales y delegarlas al equipo. Antes de esa instrucción pasaron 138 pruebas de API+AI, sin omisiones, usando PostgreSQL 17/pgvector desechable. Los cambios posteriores de Rerank, preferencia de gráfico, tratamiento de errores y empaquetado no se ejecutaron.

La evaluación real de 10 preguntas, antes del reranker, obtuvo 60% de casos correctos, 50% de evidencia esperada en 8 positivos y abstención correcta en los 2 negativos. BASS-II mostró pasajes secundarios en vez de los pasajes esperados. Se añadió Rerank opcional con una bolsa mayor de candidatos para corregir esa pérdida; queda sin medir. No confundir generación activa con calidad documental aceptada.

1. Instalar dependencias e iniciar API y servicio privado. Ejecutar las suites del repositorio y el build de ambas imágenes; regenerar/comprobar OpenAPI si cambia el contrato público.
2. Evaluar las dos fuentes: `python ai/scripts/evaluate_engine.py --cases ai/evaluations/ntrs_20130014061_candidates.json ai/evaluations/ntrs_20160000593_candidates.json`. Para comparar el reranker, añadir `COHERE_RERANK_MODEL=rerank-v5.0-pro` al servicio IA y repetir los mismos casos. Es una dependencia opcional, desactivada en la plantilla hasta su aceptación. No ajustar las expectativas para ocultar fallos.
3. Con `PYROGRAVITY_DATABASE_URL` disponible al operador, ejecutar `python scripts/verify_live_ai.py --base-url https://<api-publica>`. Comprueba los cinco análisis, una comparación con puntos reales, una explicación documental y abstención. Usa servicios reales y puede consumir Cohere. No se ejecutó en esta sesión.
4. Desde la web, repetir esos recorridos y comprobar cita, página, literal, unidad, limitaciones y `request_id`. Confirmar que no se ve procedencia `demo`.
5. En un entorno de aceptación, probar token ausente/incorrecto (401), proveedor caído/timeout (503/504), referencia alterada (502), ensayo inexistente (404) y acceso de cada login. Restaurar la configuración del proveedor después de probar fallos.

Conservar el SHA desplegado y los resultados. Para revertir la KB, cambiar el puntero `ai.kb_active` a la generación sellada previa `815aa64a-1f52-4120-bfd9-95a375729e77`; no borrar los documentos. La reversión de código usa la imagen anterior.
