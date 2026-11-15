# Contrato v1.1 propuesto para backend, IA y catálogo científico

Estado: **borrador para revisión de Gregori, Stanley, Bryant y Michael**. V1.0 permanece en `schemas/contracts.py` y `contracts/v1/`; v1.1 vive en `schemas/contracts_v11.py` y `contracts/v1_1/`. Los JSON Schema exportados son el artefacto de intercambio. Nadie ha adoptado aún esta versión ni existe el endpoint de IA real.

**Bloqueos conocidos antes de aprobar v1.1:** el límite actual de cinco ensayos y la exigencia de `experiment_ids` impiden algunas comparaciones/cohortes; falta distinguir la respuesta pública enriquecida que recibe Bryant de la respuesta interna; `ChartSpec` debe recuperar reglas de tipo de eje, unidades y respaldo científico. Estos puntos se revisan con el equipo; este borrador no se debe usar como contrato definitivo.

## Consulta y respuesta

- `POST /internal/v1/ai/query` recibe `AiQueryRequest` y devuelve `AiResponse` (HTTP 200) o `ErrorEnvelope` (HTTP no 200). Ruta propuesta; autenticación y despliegue se acuerdan con Michael. El servicio será interno, sobre TLS y con autenticación entre servicios. El frontend nunca lo llama directamente.
- El backend genera `request_id`, valida la selección y pasa `ScientificResult` ya verificados y `chart_refs` autorizados. `query_type` es una pista opcional; `analysis_id` y `filters` son alcance opcional. Solo BASS-II admite filtros de entrada `pi` y `material`. `experiment_ids` tiene máximo cinco códigos `PSI-69:psi-69_flex:1`; `source_record` empieza en uno tras la cabecera.
- Si no hay ensayos seleccionados, el backend no envía resultados científicos ni gráficos. La IA responde con evidencia documental o `insufficient_evidence`. No inventa mediciones ni ejecuta un análisis científico implícito.
- `AiResponse.status` tiene solo `supported`, `partially_supported` e `insufficient_evidence`. Errores de transporte, autenticación o proveedores van en HTTP y `ErrorEnvelope`. El backend añade por fuera su procedencia `vivo`, `caché`, `demo` o `degradado`.
- Cada `Claim` referencia `evidence[]` por ID. Un claim numérico requiere evidencia científica. La evidencia científica referencia `result_id` y `datum_id` de un resultado enviado por el backend; el backend verifica valor, unidad y procedencia contra sus datos. La evidencia documental contiene `Citation`.

## Citas y lectura del corpus

`Citation` contiene `document_id`, `document_sha256`, `page_number`, `passage_id`, `passage_sha256`, `quote` literal y `source_id`. El backend consulta la vista propuesta `ai.citation_passages` por `passage_id`, compara esos campos y exige que `quote` esté contenida literalmente en `passage_text`. La vista devuelve, exactamente: `passage_id`, `document_id`, `document_sha256`, `page_number`, `passage_sha256`, `passage_text`, `extraction_version`, `source_id`, `source_title`, `source_url`. Solo incluye documentos y fuentes revisados. La comprobación semántica del apoyo a una afirmación requiere casos revisados por personas.

Johan mantiene el borrador SQL bajo `ai/migrations/`; el responsable de migraciones compartidas debe incorporarlo a `supabase/migrations/` después de revisarlo. Ningún rol tiene acceso a la vista en este borrador. Se acordará un rol de servidor de solo lectura, con `USAGE` en `ai` y `SELECT` solo en la vista, antes de desplegarla. No utilizar `anon`, `authenticated`, `service_role` ni `postgres` como lector de la aplicación.

## Resultados científicos

`ScientificResult` contiene `result_id`, `data_version`, `analysis_id`, estado `ok|partial|insufficient_evidence`, `source`, `datasets[]`, `data[]`, advertencias y limitaciones. `data_version` será el SHA-256 de una serialización JSON canónica del resultado científico normalizado, excluyendo `result_id`, `data_version` y `source`; el adaptador debe calcularlo y comprobarlo, no inventarlo. Cada dataset lleva `psi_code`, `table_name`, ruta relativa, SHA-256 del archivo, fuente y `database_dataset_id` opcional. Esto admite varios datasets en una respuesta.

Una medición validada exige dataset, código de ensayo, `source_record`, ordinal y cabecera de columna, valor decimal como cadena, valor original, unidad e interpretación `exact`. Para una cantidad adimensional verificada se usa unidad `"1"`; unidad desconocida no se marca `validated`. Un derivado validado exige datasets de entrada, método y versión, `sample_count`, grupo/cohorte/filtros y trazabilidad: referencias a celdas para cálculos puntuales o hash del conjunto ordenado de entradas para agregados. Un delta requiere dos celdas y `sample_count=1` observación emparejada. `validated` avala trazabilidad y operación, no causalidad física. El adaptador sigue pendiente de implementación y acuerdo con Stanley.

`ok` admite limitaciones científicas; `partial` tiene al menos un dato admisible pero cobertura incompleta; `insufficient_evidence` no contiene datos admisibles. Solo datos validados entran en `data[]`. Las selecciones de resultados precomputados de FLEX, Flame Design, CFI-G y SPICE no son filtros de entrada ni recalculan estadística.

### Condiciones pendientes con Stanley

Stanley considera viable v1.1 mediante un adaptador independiente de `Scientific Catalog`, sin modificar ETL ni análisis originales, pero su aceptación es condicional. Antes de implementar ese adaptador, Johan y Stanley deben fijar: (1) estados de interpretación, marcas de calidad y criterios de inclusión que permiten `validated`; (2) catálogo de métodos derivados y versiones, `sample_count`, referencias a celdas y hash reproducible de conjuntos de entrada; (3) serialización canónica de `data_version`, con orden de registros, representación Decimal y exclusión o normalización de IDs específicos de PostgreSQL, para que Parquet y Supabase den el mismo hash con evidencia equivalente; (4) mapeo de `experiment_ids`, `source_header` y `dataset_ref_id` a los metadatos reales. `pi` y `material` siguen siendo los únicos filtros de entrada. Las limitaciones de CFI-G y SPICE deben viajar explícitas en el resultado. Hasta cerrar estas reglas, el adaptador no debe emitir `validated` por inferencia.

## Gráficos y errores

Cada `ChartRef` de entrada tiene `data_ref`, etiqueta, variable, unidad y códigos de ensayo. `ChartSpec` solo usa un `data_ref` suministrado y mantiene variable y unidad coincidentes; el backend resuelve los puntos y rechaza referencias ajenas. `chart_preference=required` expresa la preferencia; nunca obliga a fabricar una serie. `validate_response_against_request()` comprueba referencias cruzadas que JSON Schema no expresa.

| HTTP | `error.code` | Uso |
| --- | --- | --- |
| 422 | `invalid_request` | Solicitud o contrato inválido |
| 401 / 403 | `unauthorized` / `forbidden` | Autenticación o autorización entre servicios |
| 429 | `rate_limited` | Límite de peticiones |
| 503 | `upstream_unavailable` | Cohere, base o corpus requerido indisponible |
| 504 | `timeout` | Tiempo agotado |
| 500 | `internal_error` | Error interno sin detalles sensibles |

El error tiene `schema_version`, `request_id` cuando se pudo extraer, y `error: {code, message, retryable}`. No incluir claves, DSN, prompts, contenido del corpus ni trazas. El backend mapea estos códigos a su sobre HTTP y decide cualquier recuperación con caché o demo, dejando su procedencia explícita.

Generar y comprobar: `python ai/scripts/export_contracts.py`, `python ai/scripts/export_contracts.py --check`, `python -m pytest ai/tests/test_contracts_v11.py -q`. Los ejemplos son sintéticos.
