# Calidad de extracción del primer documento NASA

Fuente: NTRS 20130014061; PDF fijado por SHA-256 en `sources/ntrs_20130014061.json`. Extracción actual: `pypdf-7.0.0-header-v1`.

- Se extrajeron 11 páginas con texto y 33 fragmentos, sin caracteres de reemplazo. El hash del PDF coincide con el manifiesto.
- El encabezado de congreso idéntico al inicio de 10 páginas se elimina antes de crear fragmentos. La regla se aplica solo a primeras líneas idénticas de 20 o más caracteres presentes en al menos la mitad de tres o más páginas. Páginas y offsets corresponden al texto limpio.
- La ecuación (1) de la página 5 se lee en mejor orden que con el extractor anterior, pero las fórmulas y las tablas requieren cotejo visual con el PDF original. Ningún fragmento se marca `reviewed` por esta inspección automática.
- Inspección visual del PDF fijado (2026-11-15): página 5 confirma que sustituir CO₂ por He aumenta la tasa de combustión y atribuye el cambio a la mayor conductividad térmica; la ecuación (1) y sus símbolos se ven legibles en el original. Página 9 confirma que la figura 5 compara diámetro de extinción (`D_ext`) con diámetro inicial (`D_0`), y que el tamaño de los círculos representa la fracción molar ambiental de oxígeno. Página 11 habla de una predicción singular: el diámetro de extinción mediante asintótica de energía de activación necesita una mejora considerable. El caso de evaluación se cambió a singular para corresponder al texto. La búsqueda de `BASS`/`BASS-II` en las once páginas extraídas no halló coincidencias, lo que apoya el caso negativo de alcance documental.
- Esta comprobación visual respalda la pertinencia de las cuatro preguntas positivas y la ausencia de BASS en este artículo, pero no es aprobación humana del benchmark ni revisión completa de todas las ecuaciones, tablas y páginas. Los cinco casos conservan estado `candidate`; las métricas siguen bloqueadas hasta que una persona revise y registre cada decisión.

Cambiar el extractor o la limpieza cambia `extraction_version` y exige regenerar fragmentos, hashes y embeddings. Antes de indexar, revisar manualmente citas, ecuaciones y tablas de cada página y registrar quién aprobó el documento.
