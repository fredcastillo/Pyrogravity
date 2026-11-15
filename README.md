# Pyrogravity · Flame in Freefall

**Prototipo del NASA Space Apps Challenge 2026.** Pyrogravity busca convertir datos de combustión en microgravedad en comparaciones, gráficos interactivos y explicaciones que citen su evidencia. El repositorio contiene la estructura inicial y la configuración de colaboración. [Ver el reto](https://www.spaceappschallenge.org/2026/challenges/flame-in-freefall/) · [Ver GitHub Actions](https://github.com/fredcastillo/Pyrogravity/actions)

## Cómo se conectan las piezas

1. Datos procesa una muestra versionada de NASA y entrega mediciones, estadísticas, unidades y procedencia.
2. El motor de IA consulta esos resultados para responder preguntas numéricas y recupera pasajes de documentos para las explicaciones. Cohere Command A es el candidato para la generación. PostgreSQL puede reunir los datos y el corpus, con pgvector si las pruebas muestran que mejora la recuperación.
3. FastAPI expone los resultados de PostgreSQL/Supabase, las citas y, cuando corresponde, una especificación gráfica vinculada a los valores que calculó el módulo científico.
4. El dashboard permite filtrar, comparar y explorar los gráficos. La demo usará un conjunto local de datos y respuestas verificadas cuando los servicios externos estén caídos.

## Fuentes científicas

| Investigación | Fuente de los datos | Documentación experimental |
| --- | --- | --- |
| FLEX · combustión de gotas líquidas | [PSI-69 v5 · DOI 10.60555/mbq8-0451](https://psi.nasa.gov/physci/repo/data/investigations/PSI-69) | [Resultados de FLEX](https://ntrs.nasa.gov/citations/20150023456) |
| BASS-II · combustión de sólidos | [PSI-25 v4 · DOI 10.60555/4qc4-de67](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25) | [Informe de BASS-II](https://ntrs.nasa.gov/citations/20210011385) |

En NASA PSI, los CSV ligeros están en **Data files and documents → Experimental table**. Conservamos DOI, versión del dataset, ensayo, fila y unidad en los resultados numéricos. Las citas documentales incluyen página o sección.

## Equipo

| Integrante | Área | Ruta y rama de trabajo |
| --- | --- | --- |
| Stanley Camacho · [@StanleyCM](https://github.com/StanleyCM) | ETL y consultas científicas | data/ · users/stanley |
| Johan Gabriel Vasquez · [@Johanvasquezdev](https://github.com/Johanvasquezdev) | IA, RAG, citas y especificación gráfica | rag/ · users/johan |
| Gregori Jimenez · [@GregoriEJimenezDev](https://github.com/GregoriEJimenezDev) | FastAPI, contratos e integración de servicios | backend/ · users/gregori |
| Bryant Romano · [@Brlamafia](https://github.com/Brlamafia) | Dashboard y visualizaciones | frontend/ · users/bryant |
| Fred Sneyder Castillo · [@fredcastillo](https://github.com/fredcastillo) | QA, seguridad y trazabilidad científica | tests/ · users/sneyder |
| Michael Robles · [@iClexi](https://github.com/iClexi) | Docker, CI, despliegue y recuperación | infrastructure/ · users/michael |

Usamos pull requests hacia **main** para integrar cambios. La [guía de contribución](CONTRIBUTING.md) explica cómo abrirlos y qué verifica CI.

## Recorrido de la demo

- Consultar la duración de un ensayo FLEX y mostrar su fuente.
- Responder una pregunta conceptual y citar la sección de un documento NASA que la respalda.
- Comparar ensayos compatibles y mostrar una gráfica con unidades, filtros y procedencia.
- Explicar qué evidencia falta cuando los datos no permiten responder una pregunta.
