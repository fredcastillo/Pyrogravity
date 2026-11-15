# Pyrogravity: diseño y preparación del MVP

**Estado:** propuesta para revisión del equipo, 4 de noviembre de 2026. Este documento define decisiones de diseño y tareas de investigación. La implementación de la solución empieza cuando lo permitan las reglas del hackathon.

## 1. Objetivo y límite del producto

El usuario de la demostración debe poder encontrar un ensayo de combustión en microgravedad, ver sus mediciones con unidades y fuentes, comparar ensayos compatibles, y recibir una explicación asistida por IA que distinga observaciones de interpretaciones. El reto oficial pide un dashboard que resuma, ordene e interprete hallazgos; el ordenamiento necesita una métrica científica explícita y condiciones comparables.

**MVP de la demostración:**

1. Consultar un ensayo FLEX por identificador y mostrar un valor medido con unidad y procedencia.
2. Explicar un concepto de combustión en microgravedad a partir de un documento NASA localizable.
3. Comparar y ordenar un grupo homogéneo de ensayos por una métrica disponible, mostrando N, filtros y un gráfico.
4. Responder una pregunta sin soporte suficiente mediante abstención o respuesta parcial.
5. Mostrar al menos un registro documentado de BASS-II. La comparación numérica entre FLEX y BASS-II se habilita únicamente para variables y condiciones que Stanley valide como compatibles.

Quedan fuera del MVP: predicción certificada de riesgo, causalidad no demostrada, análisis de vídeo, entrenamiento de modelos, agentes con herramientas amplias y gráficos generados como código por un LLM.

## 2. Decisiones de arquitectura propuestas

| Tema | Decisión para el MVP | Motivo o condición |
| --- | --- | --- |
| API | FastAPI, a cargo de Gregori | Coincide con el plan de backend y el lenguaje de los módulos de datos e IA. |
| Motor de IA | Paquete Python `ai/` invocado por la API mediante un puerto `AIEngine` | Mantiene un despliegue sencillo; si surge una necesidad demostrada de separación, el mismo contrato admite HTTP. |
| Datos | PostgreSQL gestionado en Supabase, con un único catálogo de fuentes e identificadores compartidos | La base científica y el índice documental tienen responsabilidades lógicas distintas, aunque compartan instancia. |
| Ingesta | Procesos por lotes separados de las solicitudes de usuarios | Stanley publica datos procesados; Johan indexa documentos aprobados. Ninguno modifica archivos originales. |
| Recuperación | Búsqueda textual y filtro por fuente/versión como línea base | Añadir embeddings, pgvector o reranking solo si mejoran preguntas etiquetadas. |
| Generación | Proveedor de LLM detrás de un adaptador de Johan | El modelo definitivo se elige con pruebas de exactitud, citas, latencia, disponibilidad y costo. |
| Gráficos | `ChartSpec` validado y `data_ref` a puntos calculados | Bryant renderiza; el modelo no inventa series ni ejecuta código. |
| Respaldo | Snapshot local con datos y respuestas aprobados para las cuatro consultas de demostración | Debe funcionar sin Supabase ni proveedor de IA y estar claramente identificado como respaldo. |

Flujo de una pregunta: **dashboard → API → AIEngine → ruta de consulta científica y/o recuperación documental → generación opcional → validación → AiResponse → dashboard**. Para una consulta numérica inequívoca se devuelve el resultado científico sin LLM. El backend transporta y valida el contrato HTTP; Johan decide la ruta y compone la respuesta; Stanley es responsable de los cálculos y mediciones.

## 3. Datos científicos y procedencia

Fuentes candidatas: [NASA FLEX, PSI-69, DOI 10.60555/mbq8-0451](https://psi.nasa.gov/physci/repo/data/investigations/PSI-69) y [NASA BASS-II, PSI-25, DOI 10.60555/4qc4-de67](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25). El catálogo confirma las investigaciones; el equipo todavía debe auditar los archivos descargables y su interpretación.

El inventario de Stanley y Johan registrará por archivo: URL, DOI, versión NASA, fecha de acceso, licencia, nombre, tamaño, formato, hash, método de lectura, variables, unidades, faltantes y restricciones. Cada campo publicado deberá poder rastrearse a `dataset_id`, `dataset_version`, `experiment_id` NASA, `source_id`, `source_row_id` y `variable_code`. Un UUID interno puede coexistir con el identificador NASA, pero nunca reemplazarlo en las citas.

El esquema final se cierra **después** de revisar una muestra real. Debe admitir mediciones puntuales y series temporales; `time_s` será opcional cuando el registro no sea una serie. Debe conservar valor original, valor normalizado, unidad, incertidumbre si existe y banderas de calidad. Las estadísticas derivadas registrarán método, filtros, N, versión del dataset y revisión del cálculo. Un nombre de variable común no basta para comparar experimentos: Stanley definirá reglas de compatibilidad de combustible/material, geometría, presión, oxígeno y método de medición según la pregunta.

El ranking del MVP se limitará a una métrica observada o calculada explícita, como duración **si la muestra la permite**, dentro de un subconjunto comparable. Se mostrará la dirección del orden, unidades, N, filtros y limitaciones. No se creará una puntuación general de “seguridad” sin definición y validación científica.

## 4. Contratos que deben aprobar Stanley, Johan y Gregori

### ScientificResult v1: Stanley → AIEngine y API

Debe contener `schema_version`, estado, operación permitida, parámetros y filtros aplicados, `dataset_id`, `dataset_version`, registros o puntos, unidades, N, método de cálculo cuando corresponda, procedencia por fila/variable, advertencias y errores tipados. Las operaciones iniciales son `get_experiment`, `get_measurements`, `compare_experiments`, `get_timeseries` y `get_available_variables`. No acepta SQL libre generado por usuarios o modelos.

### AiQueryRequest v1: API → AIEngine

Debe contener `request_id`, pregunta o intención explícita, IDs de ensayos seleccionados, filtros permitidos, idioma de respuesta y versiones de datos/corpus utilizadas. Se limita la longitud de la pregunta y la cantidad de ensayos. El backend no llama directamente al proveedor de LLM; invoca el motor de Johan. Las consultas de resumen y comparación pueden exponerse como rutas especializadas que usen internamente este contrato.

### AiResponse v1: AIEngine → API → dashboard

Debe contener `schema_version`, `request_id`, `status` (`supported`, `partially_supported`, `insufficient_evidence`), `intent`, respuesta, afirmaciones identificadas, evidencias enlazadas por ID, limitaciones, `visualizations` y metadatos de ejecución. Cada evidencia incluye `source_id`, DOI/URL, versión y localizador de documento/página/sección o ensayo/fila/variable; para cifras, valor y unidad. `visualizations` puede ser una lista vacía. El modo de ejecución (`live`, `cache`, `demo_fallback`) se informa aparte del estado científico.

Una pregunta válida sin evidencia devuelve `insufficient_evidence` como resultado normal. Peticiones inválidas y fallos de infraestructura usan errores HTTP tipados. Gregori y Bryant acuerdan ejemplos de ambos casos. `confidence` solo se expone si tiene una definición y calibración verificables; por defecto se omite.

### ChartSpec v1: AIEngine → frontend, mediante API

Solo permite tipos y campos aprobados. Incluye título, `data_ref`, ejes con unidades, filtros, fuente, versión y limitaciones. `data_ref` identifica puntos recuperables de un análisis científico; el LLM no proporciona puntos ni código ejecutable. Una serie sin marcas de tiempo no admite gráfico temporal. El muestreo para visualización se identifica como tal y no se reutiliza para cálculos ni citas.

## 5. Reglas del motor de IA

El enrutador reconoce cinco resultados: búsqueda exacta, análisis científico, explicación documental, consulta mixta y evidencia insuficiente. Las reglas deterministas cubren inicialmente identificadores conocidos, variables permitidas y operaciones del Query Engine. La recuperación documental usa solo fuentes aprobadas y fragmentos con localizadores verificables. El LLM recibe el texto recuperado y resultados científicos ya calculados; su salida pasa por un esquema estricto.

Antes de publicar una respuesta se comprueba que las evidencias existan y coincidan en ID, versión, campo, valor y unidad. También se revisa que cada afirmación esté vinculada a evidencia pertinente. La comprobación automática de números no demuestra por sí sola una afirmación causal; las preguntas oro y afirmaciones sensibles requieren revisión humana. Cuando falta soporte, la respuesta reconoce el límite.

El caché se consulta con una huella de pregunta normalizada, filtros, IDs, versiones de dataset y corpus, versión de instrucciones, proveedor/modelo e idioma. Solo almacena respuestas que superaron la validación. El respaldo local responde únicamente a consultas con una coincidencia explícita de huella y versiones; no ofrece una respuesta genérica para otra pregunta.

## 6. API y responsabilidades

Gregori publica como mínimo: consulta/listado y detalle de experimentos, variables y estadísticas, `POST /api/v1/ai/query`, resolución de fuentes, puntos de `data_ref` y endpoints separados de vida y disponibilidad. Los nombres y esquemas finales se aprueban con Bryant y Johan. La API aplica paginación, límites, traducción uniforme de errores y documentación OpenAPI. Johan mantiene el paquete AIEngine, el índice documental, la política de citas y sus pruebas. Stanley mantiene ETL, diccionario, Query Engine y estadísticas. Fred verifica de forma independiente cifras, citas, fallos y límites. Michael prepara el entorno de ejecución y el snapshot de respaldo.

## 7. Seguridad y estabilidad

- El navegador habla únicamente con FastAPI. Las claves de Supabase y del LLM permanecen en el servidor. Las políticas públicas de lectura de tablas se evitan salvo decisión explícita del equipo; RLS y permisos de tabla se revisan juntos.
- La ingesta y las consultas de usuario tienen credenciales y permisos separados en la medida permitida por el entorno. No se concatenan consultas SQL ni se permite que el modelo elija herramientas arbitrarias.
- Se limitan tamaño de entrada, ensayos por comparación, puntos por gráfico, tiempo de espera, concurrencia y gasto de modelo. CORS se configura para los orígenes reales del dashboard.
- Preguntas y documentos recuperados se tratan como datos no confiables. Las instrucciones presentes en documentos no tienen autoridad sobre el motor. El sistema valida la estructura de salida y ensaya casos de inyección.
- El modo demo debe arrancar sin credenciales ni red. Una caída de la base debe seleccionar el snapshot completo antes de consultar repositorios remotos. Una caída del LLM permite respuestas numéricas directas o respaldos aprobados.
- La salud de proceso y la disponibilidad de dependencias se comprueban por separado. Los logs incluyen `request_id`, ruta, latencia y código de error sin guardar secretos.

## 8. Evaluación acordada antes del evento

Preparar una matriz inicial de 12 a 20 preguntas, que puede ampliarse durante el evento. El plan maestro propone 40 a 60 para la evaluación completa; la matriz inicial es un recorte consciente para el tiempo del hackathon, sujeto a aprobación de Stanley y Fred. Cada caso especifica intención, fuente esperada, valor/unidad si corresponde, cita, gráfico esperado y condición de aprobación. Debe incluir: ID inexistente, datos faltantes, unidades incompatibles, comparación no válida, pregunta causal, documento contradictorio, cita inventada, ausencia de timestamps, fallo de modelo, fallo de base, caché obsoleta y documento con instrucciones maliciosas.

| Recorrido de demo | Respuesta esperada | Validación |
| --- | --- | --- |
| «¿Cuánto duró FLEX 20CAL10?» | 5 s, identificado como valor del catálogo NASA PSI-69 versión 5; sin gráfico. | Coinciden ID, campo, unidad y fuente. |
| «¿Qué estudia BASS-II?» | Explicación documental de objetivos y condiciones estudiadas, con referencia NASA PSI-25; sin gráfico. | Cada afirmación remite a un fragmento localizable. |
| «Ordena ensayos FLEX comparables por duración» | Ranking descriptivo con valores, unidades, N, filtros y barras. La muestra exacta la aprueba Stanley; cambios de diámetro o presión se indican como limitación. | El orden y los puntos coinciden con el Query Engine; no se presenta como ranking de seguridad. |
| «¿Cuál fue la causa exacta de la extinción de 20CAL10?» | El registro permite informar la duración y el resultado observado; si falta evidencia causal, la respuesta se abstiene de atribuir una causa. | No se inventa una explicación ni una cita. |

El resultado numérico directo debe coincidir con el registro y su unidad. Las citas deben resolver a un localizador existente y respaldar la afirmación concreta. Los gráficos deben usar puntos validados y mostrar unidades. La recuperación documental se evalúa primero sobre preguntas etiquetadas; pgvector y reranking solo se añaden si mejoran resultados con una latencia aceptable. La elección del proveedor de LLM sigue el mismo banco de preguntas y un presupuesto definido por el equipo.

## 9. Secuencia durante el hackathon

1. **Inicio:** confirmar reglas y alcance; crear repositorio/estructura, contratos versionados y ejemplos de respuesta; fijar archivos de la muestra y responsables. El equipo trabaja en paralelo desde ese momento.
2. **Primer bloque:** Stanley procesa y verifica datos; Johan indexa documentos y desarrolla búsqueda/rutas; Gregori publica API con contratos; Bryant construye la vista sobre ejemplos; Fred y Michael preparan pruebas y arranque.
3. **Bloque de integración:** conectar Query Engine, AIEngine, API y dashboard; ejecutar las cuatro preguntas de demostración; corregir incompatibilidades de datos y JSON.
4. **Bloque final:** congelar versiones, revisar cifras y citas, probar caídas de servicios y respaldo, ensayar presentación y entregar con margen antes del cierre oficial.

El alcance opcional se considera solo cuando las cuatro consultas funcionan de punta a punta y pasan la revisión científica. Si BASS-II no ofrece una muestra estructurada utilizable a tiempo, se documenta el límite y se prioriza una demostración verificable con FLEX; el equipo decide cómo cumplir mejor el requisito del reto con los archivos disponibles.

## 10. Decisiones que requieren validación del equipo

| Decisión | Quién valida | Evidencia necesaria |
| --- | --- | --- |
| Archivos y variables definitivos de FLEX y BASS-II | Stanley + Johan | Inventario y muestra inspeccionada. |
| Métrica del primer ranking y reglas de comparabilidad | Stanley + Fred | Método y registros de ejemplo. |
| Esquema físico, permisos y forma de acceso a Supabase | Gregori + Stanley + Michael + Fred | Muestra de datos y revisión de permisos. |
| `ScientificResult`, `AiQueryRequest`, `AiResponse` y `ChartSpec` v1 | Stanley + Johan + Gregori + Bryant | Cuatro recorridos y ejemplos de éxito/error. |
| Proveedor de LLM y búsqueda vectorial | Johan + Fred | Evaluación sobre preguntas etiquetadas y presupuesto. |
| Entorno de demo y lista de respuestas de respaldo | Michael + todos | Ensayo sin red y restauración comprobada. |

**Listo para comenzar:** el equipo tiene una muestra real identificada, cuatro preguntas de demostración con evidencia esperada, contratos revisados, responsabilidades claras, acceso a herramientas y un orden de integración. La auditoría exhaustiva de archivos y el benchmark de modelos se completan durante el evento conforme a las reglas aplicables.

## Fuentes de referencia

- Plan general del equipo, `NASA_Space_Pyrogravity.pdf`, 23 de octubre de 2026.
- Plan maestro de datos e IA, `Pyrogravity_Plan_Maestro_Datos_IA.pdf`, 1 de noviembre de 2026.
- Plan de backend, `Plan_Backend_Flame_in_Freefall.pdf`, 1 de noviembre de 2026.
- [NASA Space Apps 2026: Flame in Freefall](https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/).
- [NASA PSI-69: FLEX](https://psi.nasa.gov/physci/repo/data/investigations/PSI-69).
- [NASA PSI-25: BASS-II](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25).
- [NASA Space Apps 2026: fechas y entrega](https://www.spaceappschallenge.org/2026/).
- [Supabase: seguridad de Data API](https://supabase.com/docs/guides/api/securing-your-api).
- [OWASP: prompt injection en aplicaciones LLM](https://genai.owasp.org/llmrisk/llm01-prompt-injection/).
