# Referencias y fuentes

Actualizado: 15 de noviembre de 2026. Este índice distingue datos y publicaciones oficiales de documentación técnica y lecturas introductorias. Las páginas NASA PSI identifican investigaciones; la procedencia exacta de cada CSV se registra en el manifiesto y las tablas de `data/`.

## Fuentes científicas oficiales

- [NASA Physical Sciences Informatics (PSI)](https://psi.nasa.gov/physci/repo) y [búsqueda de investigaciones](https://psi.nasa.gov/physci/repo/search?q=&data_source=psi&data_type=investigation).
- [FLEX, PSI-69](https://psi.nasa.gov/physci/repo/data/investigations/PSI-69) y [BASS-II, PSI-25](https://psi.nasa.gov/physci/repo/data/investigations/PSI-25): fuentes prioritarias de datos.
- Otras investigaciones presentes en el catálogo del ETL: [PSI-10](https://psi.nasa.gov/physci/repo/data/investigations/PSI-10), [PSI-20](https://psi.nasa.gov/physci/repo/data/investigations/PSI-20), [PSI-21](https://psi.nasa.gov/physci/repo/data/investigations/PSI-21), [PSI-22](https://psi.nasa.gov/physci/repo/data/investigations/PSI-22), [PSI-23](https://psi.nasa.gov/physci/repo/data/investigations/PSI-23), [PSI-26](https://psi.nasa.gov/physci/repo/data/investigations/PSI-26), [PSI-39](https://psi.nasa.gov/physci/repo/data/investigations/PSI-39), [PSI-47](https://psi.nasa.gov/physci/repo/data/investigations/PSI-47), [PSI-68](https://psi.nasa.gov/physci/repo/data/investigations/PSI-68), [PSI-98](https://psi.nasa.gov/physci/repo/data/investigations/PSI-98), [PSI-99](https://psi.nasa.gov/physci/repo/data/investigations/PSI-99), [PSI-100](https://psi.nasa.gov/physci/repo/data/investigations/PSI-100), [PSI-101](https://psi.nasa.gov/physci/repo/data/investigations/PSI-101), [PSI-102](https://psi.nasa.gov/physci/repo/data/investigations/PSI-102), [PSI-106](https://psi.nasa.gov/physci/repo/data/investigations/PSI-106), [PSI-107](https://psi.nasa.gov/physci/repo/data/investigations/PSI-107) y [PSI-159](https://psi.nasa.gov/physci/repo/data/investigations/PSI-159).
- [NASA Technical Reports Server (NTRS)](https://ntrs.nasa.gov/search): publicaciones experimentales. La primera fuente documental registrada en AI es [NTRS 20130014061](https://ntrs.nasa.gov/citations/20130014061), con PDF y SHA-256 fijados en el manifiesto de `ai/`.
- [NASA Open Data](https://data.nasa.gov/) y [SOFIE](https://science.nasa.gov/biological-physical/investigations/sofie/): portales de consulta adicionales; no equivalen por sí solos a un CSV validado del proyecto.

La nota recibida sobre CSV está conservada en [message.txt](message.txt). Sus etiquetas «Descargar CSV» no son enlaces descargables. El catálogo ETL actual identifica FLEX-2 como PSI-68; conservar ese identificador al relacionar datos y fuentes.

## Documentación técnica usada

- [Cohere Command A](https://docs.cohere.com/docs/command-a): modelo elegido para generación; identificador de API `command-a-03-2025`.
- [pgvector](https://github.com/pgvector/pgvector): tipo vector y búsqueda en PostgreSQL. La extensión ya está habilitada en el esquema `extensions` de Supabase.
- [Seguridad de la Data API de Supabase](https://supabase.com/docs/guides/api/securing-your-api) y [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security): permisos y acceso a esquemas privados.
- [PostgreSQL: búsqueda textual e índices](https://www.postgresql.org/docs/17/textsearch-tables.html).
- [AWS: introducción a la ingesta de datos](https://aws.amazon.com/what-is/data-ingestion/).

## Lecturas introductorias y ejemplos externos

- [Base de datos vectorial](https://www.geeksforgeeks.org/data-science/what-is-a-vector-database/) y [RAG](https://www.geeksforgeeks.org/nlp/what-is-retrieval-augmented-generation-rag/) de GeeksforGeeks: material introductorio, no evidencia científica.
- [NASA-SPACE-APPS](https://github.com/Krypton-N/NASA-SPACE-APPS) y [Fotia](https://github.com/AnteurAbderraouf/Fotia): ejemplos de terceros. No sustituyen los originales ni la validación de NASA PSI.
