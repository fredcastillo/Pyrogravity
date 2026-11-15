# Decisiones técnicas de Pyrogravity AI

Actualizado: 2026-11-14. Este archivo registra decisiones duraderas; el avance de cada sesión está en `HANDOFF.md`.

## D-001 · Un repositorio, propiedad por módulo

**Decisión:** trabajar en la rama `users/johan` del mismo repositorio, solo dentro de `ai/` salvo autorización. Un Supabase compartido separa `scientific` (Stanley), `ai` (Johan) y `app` (Gregori). **Motivo:** integrar el producto sin mezclar responsabilidades. **Alternativa considerada:** bases o repositorios separados; agregarían sincronización y contratos duplicados. Los cambios en CI y archivos raíz los coordina el usuario con Michael.

## D-002 · RAG documental + Scientific Query Engine

**Decisión:** recuperar pasajes para explicaciones y consultar resultados validados de Stanley para cifras. Cohere redacta a partir de ambas evidencias y la salida se valida antes de presentarla. **Motivo:** el texto documental no es una fuente confiable para calcular estadísticas de CSV. **Alternativa:** dejar que el LLM responda directamente con documentos o tablas; permitiría cifras sin procedencia. La interfaz con `scientific` sigue pendiente de acuerdo.

## D-003 · Procedencia versionada

**Decisión:** separar la identidad de la publicación NASA del PDF descargado (SHA-256), y conservar página y hash de texto por fragmento. DOI y versión declarada son opcionales. **Motivo:** una URL puede servir bytes distintos y la cita debe localizar evidencia exacta. **Alternativa:** guardar solo URL y título; insuficiente para reproducir respuestas. Diseño detallado en `source-registry.md`. El primer registro verificado es NTRS 20130014061; aún no está indexado.

## D-004 · Adaptadores simples y pruebas aisladas

**Decisión:** paquete Python 3.12 bajo `ai/src`, adaptador Cohere Chat v2, configuración Pydantic y pruebas con clientes falsos. El diagnóstico de Psycopg es de solo lectura y exige TLS. **Motivo:** aislar dependencias externas y evitar que las pruebas de PR requieran secretos. **Alternativa:** llamar SDKs y SQL desde rutas de API; dificultaría pruebas, límites y manejo de errores. No se agregó framework de orquestación.

## D-005 · Estado real de pgvector

**Estado verificado:** en una primera lectura del 2026-11-14 `vector` estaba disponible sin instalar. Una lectura posterior del mismo día confirmó `vector` 0.8.2 habilitado en `extensions`; el esquema `ai` seguía sin tablas. Este agente no hizo cambios remotos. **Decisión:** usar esa extensión para los futuros vectores en `ai` y revisar las migraciones y permisos con el equipo antes de escribir. **Alternativa:** recuperación textual sin vectores; no cumple la arquitectura acordada.

## D-006 · Control de cambios por el usuario

**Decisión:** desde la solicitud de handoff, ningún agente crea commits, pushes ni merges por iniciativa propia. **Motivo:** el usuario quiere revisar cada tramo y controlar su publicación. **Alternativa:** commits automáticos por hito, usada antes de esta decisión y ahora descartada.

## D-007 · Historial Git legible

**Decisión:** los próximos commits autorizados llevarán un tipo (`feat`, `fix`, `change`, `chore`, `docs` o `test`) y alcance `ai`. Los PR describirán archivos, motivo y pruebas. No se agregará al agente como autor, coautor ni colaborador. **Motivo:** facilitar revisión del trabajo de equipo y mantener la autoría bajo la identidad Git del usuario. **Alternativa:** mensajes libres o un commit para todo el motor; dificultarían revisar y revertir cambios concretos.

## D-008 · Primera ingesta verificable

**Decisión:** fijar el SHA-256 del PDF NASA, aceptar solo su URL HTTPS oficial, limitar la descarga a 20 MB y extraer texto por página con PyMuPDF 2.1. Los fragmentos tienen un máximo de 180 palabras, 25 de solapamiento y conservan página, offsets de caracteres y hash del texto. Solo se normalizan ligaduras tipográficas para mantener símbolos científicos. **Motivo:** poder reproducir la ingesta y citar una página sin mezclar contenido de otras. **Alternativa:** cortar el PDF completo en bloques uniformes; perdería los límites de página y facilitaría citas ambiguas. La calidad semántica de los fragmentos requiere revisión humana antes de indexarlos.

## D-009 · Esquema documental de cinco tablas

**Propuesta pendiente de revisión:** `sources`, `documents`, `document_chunks`, `chunk_embeddings` e `ingestion_jobs` dentro de `ai`. Separar texto y embeddings permite reindexar modelos sin perder fragmentos. Los chunks actuales pertenecen a una sola página; la base debe registrar `page_number` y offsets, no un rango ficticio. **Alternativa:** embedding dentro de `document_chunks`, más simple pero menos flexible para comparar modelos. `document_investigations`, `retrieval_evaluations` y `query_traces` quedan condicionadas a contratos y necesidades reales. Campos y restricciones en `database-schema.md`. No se ejecutó SQL.
