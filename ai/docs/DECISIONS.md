# Decisiones técnicas de Pyrogravity AI

Actualizado: 2026-11-15. Este archivo registra decisiones duraderas; el avance de cada sesión está en `HANDOFF.md`.

## D-001 · Un repositorio, propiedad por módulo

**Decisión:** trabajar en la rama `users/johan` del mismo repositorio, solo dentro de `ai/` salvo autorización. Un Supabase compartido separa `scientific` (Stanley), `ai` (Johan) y `app` (Gregori). **Motivo:** integrar el producto sin mezclar responsabilidades. **Alternativa considerada:** bases o repositorios separados; agregarían sincronización y contratos duplicados. Los cambios en CI y archivos raíz los coordina el usuario con Michael.

## D-002 · RAG documental + Scientific Query Engine

**Decisión:** recuperar pasajes para explicaciones y consultar resultados validados de Stanley para cifras. Cohere redacta a partir de ambas evidencias y la salida se valida antes de presentarla. **Motivo:** el texto documental no es una fuente confiable para calcular estadísticas de CSV. **Alternativa:** dejar que el LLM responda directamente con documentos o tablas; permitiría cifras sin procedencia. La interfaz con `scientific` sigue pendiente de acuerdo.

## D-003 · Procedencia versionada

**Decisión:** separar la identidad de la publicación NASA del PDF descargado (SHA-256), y conservar página y hash de texto por fragmento. DOI y versión declarada son opcionales. **Motivo:** una URL puede servir bytes distintos y la cita debe localizar evidencia exacta. **Alternativa:** guardar solo URL y título; insuficiente para reproducir respuestas. Diseño detallado en `source-registry.md`. El primer registro verificado es NTRS 20130014061; aún no está indexado.

## D-004 · Adaptadores simples y pruebas aisladas

**Decisión:** paquete Python 3.12 bajo `ai/src`, adaptador Cohere Chat v2, configuración Pydantic y pruebas con clientes falsos. El diagnóstico de Psycopg es de solo lectura y exige TLS. **Motivo:** aislar dependencias externas y evitar que las pruebas de PR requieran secretos. **Alternativa:** llamar SDKs y SQL desde rutas de API; dificultaría pruebas, límites y manejo de errores. No se agregó framework de orquestación.

## D-005 · Estado real de pgvector

**Estado verificado:** `vector` 0.8.2 está habilitado en `extensions`. El 2026-11-15 se aplicó la migración inicial de cinco tablas de `ai`; no se insertaron documentos ni embeddings. La elección de recuperación híbrida como estrategia final requiere comparar su calidad con búsqueda textual, según el Plan Maestro. **Alternativa:** recuperación textual sola; sigue siendo una línea base válida para esa evaluación.

## D-006 · Control de cambios por el usuario

**Decisión:** desde la solicitud de handoff, ningún agente crea commits, pushes ni merges por iniciativa propia. **Motivo:** el usuario quiere revisar cada tramo y controlar su publicación. **Alternativa:** commits automáticos por hito, usada antes de esta decisión y ahora descartada.

## D-007 · Historial Git legible

**Decisión:** los próximos commits autorizados llevarán un tipo (`feat`, `fix`, `change`, `chore`, `docs` o `test`) y alcance `ai`, con la descripción en español. Los PR describirán archivos, motivo y pruebas. No se agregará al agente como autor, coautor ni colaborador. **Motivo:** facilitar revisión del trabajo de equipo y mantener la autoría bajo la identidad Git del usuario. **Alternativa:** mensajes libres o un commit para todo el motor; dificultarían revisar y revertir cambios concretos.

## D-008 · Primera ingesta verificable

**Decisión:** fijar el SHA-256 del PDF NASA, aceptar solo su URL HTTPS oficial, limitar la descarga a 20 MB y extraer texto por página con `pypdf` 7.0.0. Los fragmentos tienen un máximo de 180 palabras, 25 de solapamiento y conservan página, offsets de caracteres y hash del texto. Se normalizan ligaduras tipográficas y se eliminan únicamente encabezados idénticos al inicio de al menos la mitad de tres o más páginas. `extraction_version` identifica este método y los offsets se refieren al texto ya limpio. **Motivo:** poder reproducir la ingesta y citar una página sin mezclar contenido de otras; la comparación del PDF NASA favoreció `pypdf` y su licencia BSD reduce la incertidumbre de distribución de PyMuPDF. **Alternativas:** PyMuPDF 2.1 (AGPL) y cortar el PDF completo en bloques uniformes. Las fórmulas y la calidad semántica requieren revisión humana antes de indexar.

## D-009 · Esquema documental de cinco tablas

**Decisión aplicada:** `sources`, `documents`, `document_chunks`, `chunk_embeddings` e `ingestion_jobs` dentro de `ai`. Separar texto y embeddings permite reindexar modelos sin perder fragmentos. Los chunks actuales pertenecen a una sola página; la base registra `page_number` y offsets. **Alternativa:** embedding dentro de `document_chunks`, más simple pero menos flexible para comparar modelos. `document_investigations`, `retrieval_evaluations` y `query_traces` quedan condicionadas a contratos y necesidades reales. Campos y restricciones en `database-schema.md`. Se aplicó el SQL `20261115120000` el 2026-11-15; aún no hay datos.

La migración se conserva en `ai/migrations/` y se copió a la cadena compartida `supabase/migrations/` para aplicarla con Supabase CLI. Usa búsqueda textual GIN y vectorial exacta al inicio; HNSW queda para una decisión basada en mediciones. RLS y revocación de roles Data API dejan el esquema cerrado hasta definir credenciales de servicio. **Alternativas consideradas:** activar políticas genéricas o índice HNSW antes de disponer de roles y corpus; ambas adelantarían decisiones sin evidencia.

## D-010 · Contratos de integración versionados (propuesta P1)

**Decisión de diseño:** definir `AiQueryRequest`, `ScientificResult`, `ChartSpec` y `AiResponse` como modelos Pydantic con JSON Schema y ejemplos sintéticos bajo `ai/contracts/v1/`. Es una propuesta para revisión del equipo, no una afirmación de que Stanley, Gregori o Bryant ya la hayan adoptado. `ScientificResult` es la salida normalizada futura del adaptador al catálogo, no el formato actual de `run_analysis()`. La identidad del dataset separa `psi_code`, clave BIGINT opcional y SHA-256 del archivo. Las cantidades viajan como cadenas decimales con unidad y procedencia; `data_ref` es opaco. **Motivo:** permitir integración entre lenguajes y detectar referencias, estados y unidades inválidos antes de mostrar respuestas. **Alternativa:** pasar el diccionario variable del catálogo directamente al frontend; acoplaría la interfaz a cada análisis y dificultaría validar evidencia. La estrategia de routing está en D-012.

## D-011 · Contrato v1.1 de evidencia entre servicios (propuesta)

**Decisión de diseño pendiente de integración:** el backend envía a la IA ensayos seleccionados, resultados científicos ya comprobados y referencias de gráfico autorizadas. La IA devuelve afirmaciones con identificadores de evidencia documental o científica; el backend comprueba los identificadores y valores antes de exponer la respuesta. `Citation` separa documento, versión SHA-256, página, pasaje, hash y cita literal. Los estados de contenido son `supported`, `partially_supported` e `insufficient_evidence`; los fallos operativos se expresan con HTTP y `ErrorEnvelope`. Sin ensayos seleccionados solo se admite evidencia documental. La vista privada `ai.citation_passages` está versionada en `ai/` sin permisos hasta acordar el rol lector. **Motivo:** evitar cifras o gráficos no suministrados por la fuente científica y permitir una comprobación literal reproducible de citas. **Alternativas:** que la IA consulte directamente `scientific` o que el backend le envíe pasajes sin que la IA haga recuperación; ambas cambian la responsabilidad acordada del RAG o duplican validación. El servicio interno existe y pasó pruebas locales; todavía no está conectado al backend ni desplegado.

## D-012 · Routing híbrido de intenciones

**Decisión:** opción C: clasificar primero con reglas explícitas para casos claros y consultar Cohere como respaldo cuando la intención sea ambigua. Si ninguna ruta tiene evidencia suficiente, responder `insufficient_evidence`. **Motivo:** mantener rutas científicas y documentales comprobables sin depender de una clasificación generativa en todas las preguntas. **Alternativas:** solo reglas (cobertura limitada) o solo modelo (menos determinismo). Falta cerrar el mapeo entre `query_type`, `intent` y las categorías del Plan Maestro antes de implementar el orquestador.

## D-013 · Persistencia de ingesta sin reemplazo implícito

**Decisión:** construir un plan reproducible antes de escribir y persistir fuente, PDF, fragmentos, vectores y job en una transacción. Una repetición del mismo plan conserva fragmentos y embeddings; el esquema inicial rechaza una extracción distinta del mismo PDF. El documento queda `extracted`, nunca `reviewed` por código. La función exige un rol dedicado que no sea superusuario, `BYPASSRLS` ni dueño de las tablas. **Motivo:** evitar mezclas de evidencia y cambios silenciosos en citas. **Alternativa:** sobrescribir filas con `ON CONFLICT DO UPDATE`; impediría volver a la versión previa. D-015 propone conservar configuraciones distintas en generaciones separadas; aún no está desplegado.

## D-014 · Recuperación medible sobre documentos revisados

**Decisión:** usar búsqueda textual inglesa con `plainto_tsquery` y, si no da resultados, una segunda pasada OR sobre términos sanitizados; mantener similitud coseno exacta por `config_hash`. RRF sigue como candidato y no se activa por defecto. Todas las rutas filtran fuentes `catalog_verified` y documentos `reviewed` de la generación activa. **Motivo:** la consulta estricta perdió preguntas naturales que no repetían literalmente todos los términos; el fallback mejora recall sin construir operadores desde texto sin sanitizar. **Medición inicial:** con 5 casos aprobados del PDF NTRS 20130014061, text obtuvo hit-rate@5 0.75 y MRR 0.3625; vector 1.0/1.0; RRF 1.0/0.6667. Las tres estrategias devolvieron pasajes para el caso negativo BASS-II (abstention accuracy 0). Por tanto, la prueba no justifica preferir RRF frente a vector ni define umbral de abstención. **Límite:** un PDF y tres pasajes positivos únicos son un smoke test; ampliar corpus, idiomas y negativos antes de elegir estrategia o umbrales. Evidencia detallada en `evaluations/ntrs_20130014061_run_20261115.md`.

## D-015 · Generaciones inmutables de Knowledge Base (publicadas en rama, sin desplegar)

**Decisión de diseño:** una generación reúne como máximo una extracción por fuente y una configuración de embeddings. Se sella solo si todas sus fuentes/documentos están revisados y cada pasaje tiene vector de esa configuración. Un único puntero activo selecciona la generación visible para recuperación y citas; volver a apuntar a una generación sellada permite rollback sin borrar evidencia. Una nueva `processing_config_hash` permite conservar la misma versión PDF con otro extractor, chunking o modelo, a costa de duplicar texto entre configuraciones. **Motivo:** no mezclar pasajes incompatibles ni sustituir citas históricas silenciosamente. **Alternativas:** sobrescribir filas existentes, activar por documento individual o copiar toda la base para cada versión; complican consistencia o recuperación. La migración y las pruebas están solo en `ai/`; faltan revisión de roles y publicación compartida antes de desplegar.

## D-016 · Canonicalización científica explícita (publicada en rama v1.1)

**Decisión de diseño:** `data_version` usa `scientific-result-c14n-v1`, visible en el objeto. Excluye exactamente `result_id`, `data_version`, `source` y `datasets[].database_dataset_id` del JSON usado para SHA-256; el último permanece en la respuesta. `DatasetRef.ref_id` deriva de PSI, ruta y SHA-256, no de PostgreSQL. Los derivados agregados guardan su hash en `input_set_sha256` y declaran `input_set_version=scientific-input-set-c14n-v1`; sus entradas tienen un formato fijo, con valores decimales normalizados y texto CSV literal. **Motivo:** permitir paridad verificable entre Parquet y PostgreSQL y evitar que un campo de almacenamiento cambie el hash científico. **Alternativa:** excluir genéricamente cualquier campo “del motor”; sería ambiguo y permitiría divergencias silenciosas. Algoritmo y vectores sintéticos en `scientific-canonical-v1.md` y `contracts/v1_1/`. Stanley publicó su adaptador con paridad Parquet/PostgreSQL reportada en el PR #32; aún falta integrarlo en `main` y ejecutarlo en el CI conjunto.

## D-017 · Selección generativa con respuesta acotada por evidencia

**Decisión:** el orquestador usa reglas para rutas claras y Command A para clasificar ambigüedad y seleccionar IDs de evidencia entre candidatos limitados. El texto final de cada afirmación se construye con cifras del `ScientificResult` recibido o con citas literales de pasajes revisados; el modelo no puede crear referencias, números ni gráficos. El endpoint interno exige token y devuelve errores técnicos por HTTP. **Motivo:** la validación estructural puede comprobar IDs, hashes y valores, pero no demostrar que una paráfrasis libre esté respaldada semánticamente. **Alternativa:** publicar directamente la prosa generada por el modelo; permitiría afirmaciones no verificables. El backend debe seguir comprobando las citas y cifras antes de exponerlas.

## D-018 · Alcance científico por ensayo antes de enviar a IA

**Decisión:** un resultado completo de Stanley se reduce a las mediciones de los ensayos y variables solicitados antes de construir `AiQueryRequest`. Solo se conservan derivados puntuales cuyas celdas de entrada pertenecen a esos ensayos; los agregados que solo tienen `input_set_sha256` no demuestran ese alcance. Se recalcula `data_version` sobre el subconjunto con la canonicalización v1.1. **Motivo:** impedir que una pregunta sobre un ensayo reciba evidencia de otros ensayos sin cambiar la procedencia original. **Alternativa:** enviar el análisis completo y filtrar después de Cohere; expondría datos ajenos al alcance y el contrato interno ya rechaza mediciones no seleccionadas. `scope_scientific_result` es la implementación de referencia en `ai/`; Gregori debe aplicar y verificar el mismo límite al construir el request remoto.

## D-019 · Evaluación end-to-end de evidencia y abstención

**Decisión:** evaluar por separado el recuperador y el motor completo. Para cada pregunta revisada, el evaluador end-to-end compara el estado final y los pasajes elegidos con la identidad aprobada de fuente, PDF y fragmento. En preguntas negativas, solo cuenta como abstención correcta `insufficient_evidence` sin afirmaciones, evidencia ni gráficos. No se fija un umbral de similitud ni un criterio de producción hasta tener fuentes, idiomas y negativos suficientes. **Motivo:** un recuperador puede devolver distractores aunque el motor después se abstenga; hit-rate de recuperación no mide la decisión final de Command A. **Alternativa:** usar solo métricas de recuperación o elegir un umbral de similitud con cinco casos; ambas ocultarían errores de selección y serían insuficientes para calibrar producción. Herramienta: `scripts/evaluate_engine.py`; requiere una generación activa revisada, rol de solo lectura y uso real de Cohere.

## D-020 · Evaluación documental de varias fuentes

**Decisión:** cada PDF conserva sus casos y sus hashes de evidencia en un archivo separado; las herramientas aceptan varios archivos solo si pertenecen a la misma generación activa. Los totales se calculan a partir de los casos individuales, no promediando porcentajes de fuentes con distintos tamaños. Los casos `candidate` bloquean la medición. **Motivo:** medir distractores entre documentos y evitar que el primer artículo FLEX represente la calidad de todo el corpus. **Alternativa:** combinar preguntas de fuentes distintas sin verificar la generación activa; permitiría resultados no reproducibles.


## D-021 · Conexión científica por el catálogo PostgreSQL y entrega operativa

El backend usa el adaptador independiente de Stanley con `source="postgres"` para los cinco análisis y un lector dedicado; limita resultados a IDs y variables y recalcula el hash. Se conserva el contrato público. Se evita ejecutar ETL/Parquet por petición, alternativa que solo cubría FLEX. El servicio AI se despliega separado, autenticado y detrás de HTTPS privado; runtime no recibe permisos de ingesta ni administrador.

La selección Cohere usa JSON mode, manteniendo rechazo de IDs o formas inválidas. Las afirmaciones numéricas contienen valor/unidad; la procedencia y los métodos viajan en las referencias. Esto evita que la comprobación de cifras confunda identificadores o versiones con mediciones.

La evaluación de dos fuentes mostró pérdida de pasajes BASS-II en el top reducido. Se incorpora Rerank opcional sobre un pool más amplio, desactivado por defecto hasta la evaluación del equipo. Alternativa: declarar suficiente el resultado de un solo PDF; no representa el corpus ampliado. No se establece umbral de calidad a partir de diez casos.

## D-022 · Pertinencia antes de seleccionar evidencia

La prueba pública encontró una respuesta respaldada por un pasaje real, pero ajena a una premisa material de la pregunta. Se exige que la selección considere fenómeno, sustancia, condiciones y cantidad solicitados; compartir el nombre de la investigación no basta. La selección usa temperatura cero y conserva la validación de IDs y trazabilidad. Es una mejora de instrucción al modelo, no una garantía universal de pertinencia: se conserva la prueba negativa de aceptación y la evaluación por documento.
