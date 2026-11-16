# Calidad de extracción del primer documento NASA

Fuente: NTRS 20130014061; PDF fijado por SHA-256 en `sources/ntrs_20130014061.json`. Extracción actual: `pypdf-7.0.0-header-v1`.

- Se extrajeron 11 páginas con texto y 33 fragmentos, sin caracteres de reemplazo. El hash del PDF coincide con el manifiesto.
- El encabezado de congreso idéntico al inicio de 10 páginas se elimina antes de crear fragmentos. La regla se aplica solo a primeras líneas idénticas de 20 o más caracteres presentes en al menos la mitad de tres o más páginas. Páginas y offsets corresponden al texto limpio.
- La ecuación (1) de la página 5 se lee en mejor orden que con el extractor anterior, pero las fórmulas y las tablas requieren cotejo visual con el PDF original. Ningún fragmento se marca `reviewed` por esta inspección automática.

Cambiar el extractor o la limpieza cambia `extraction_version` y exige regenerar fragmentos, hashes y embeddings. Antes de indexar, revisar manualmente citas, ecuaciones y tablas de cada página y registrar quién aprobó el documento.
