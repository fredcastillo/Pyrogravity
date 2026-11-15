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

**Decisión de diseño pendiente de aceptación:** el backend envía a la IA ensayos seleccionados, resultados científicos ya comprobados y referencias de gráfico autorizadas. La IA devuelve afirmaciones con identificadores de evidencia documental o científica; el backend comprueba los identificadores y valores antes de exponer la respuesta. `Citation` separa documento, versión SHA-256, página, pasaje, hash y cita literal. Los estados de contenido son `supported`, `partially_supported` e `insufficient_evidence`; los fallos operativos se expresan con HTTP y `ErrorEnvelope`. Sin ensayos seleccionados solo se admite evidencia documental. Se propone una vista privada `ai.citation_passages` para comprobar citas, sin permisos hasta acordar el rol lector. **Motivo:** evitar cifras o gráficos no suministrados por la fuente científica y permitir una comprobación literal reproducible de citas. **Alternativas:** que la IA consulte directamente `scientific` o que el backend le envíe pasajes sin que la IA haga recuperación; ambas cambian la responsabilidad acordada del RAG o duplican validación. Detalle y limitaciones en `docs/contracts-v1.1.md`; todavía no existe servicio ni adopción por otros módulos.

## D-012 · Routing híbrido de intenciones

**Decisión:** opción C: clasificar primero con reglas explícitas para casos claros y consultar Cohere como respaldo cuando la intención sea ambigua. Si ninguna ruta tiene evidencia suficiente, responder `insufficient_evidence`. **Motivo:** mantener rutas científicas y documentales comprobables sin depender de una clasificación generativa en todas las preguntas. **Alternativas:** solo reglas (cobertura limitada) o solo modelo (menos determinismo). Falta cerrar el mapeo entre `query_type`, `intent` y las categorías del Plan Maestro antes de implementar el orquestador.

## D-013 · Persistencia de ingesta sin reemplazo implícito

**Decisión:** construir un plan reproducible antes de escribir y persistir fuente, PDF, fragmentos, vectores y job en una transacción. Una repetición del mismo plan conserva fragmentos y embeddings; si la extracción de un PDF ya registrado cambia, se rechaza hasta ejecutar una reindexación versionada explícita. El documento queda `extracted`, nunca `reviewed` por código. La función exige un rol dedicado que no sea superusuario, `BYPASSRLS` ni dueño de las tablas. **Motivo:** evitar mezclas de evidencia y cambios silenciosos en citas. **Alternativa:** sobrescribir filas con `ON CONFLICT DO UPDATE`; impediría volver a la versión previa. Activación y rollback de versiones de Knowledge Base aún requieren una migración adicional.

## D-014 · Recuperación medible sobre documentos revisados

**Decisión:** implementar búsqueda textual inglesa y similitud coseno exacta como líneas base, y combinación por reciprocal rank fusion como candidato. Todas filtran fuentes `catalog_verified` y documentos `reviewed`; la rama vectorial exige `config_hash` exacto. **Motivo:** comparar calidad antes de activar ranking híbrido o añadir HNSW/Rerank. **Alternativas:** elegir solo vectores o Rerank sin casos de evaluación. Hay cinco preguntas candidatas con pasajes esperados; faltan revisión humana, mediciones y regla de abstención.
