# Calidad de extracción del primer documento NASA

Fuente: NTRS 20130014061; PDF fijado por SHA-256 en `sources/ntrs_20130014061.json`. Extracción actual: `pypdf-7.0.0-header-v1`.

- Se extrajeron 11 páginas con texto y 33 fragmentos, sin caracteres de reemplazo. El hash del PDF coincide con el manifiesto.
- El encabezado de congreso idéntico al inicio de 10 páginas se elimina antes de crear fragmentos. La regla se aplica solo a primeras líneas idénticas de 20 o más caracteres presentes en al menos la mitad de tres o más páginas. Páginas y offsets corresponden al texto limpio.
- La ecuación (1) de la página 5 se lee en mejor orden que con el extractor anterior, pero las fórmulas y las tablas requieren cotejo visual con el PDF original. Ningún fragmento se marca `reviewed` por esta inspección automática.
- Inspección visual asistida del PDF fijado (2026-11-15): la página 5 dice que sustituir CO₂ por He aumenta la tasa de combustión y atribuye el cambio a la mayor conductividad térmica; la página 9 identifica los ejes de la figura 5 como diámetro de extinción e inicial; la página 11 pide mejorar la predicción del diámetro de extinción por asintótica de energía de activación. Esto respalda los cuatro casos positivos propuestos, pero las ecuaciones, los puntos del gráfico y el resto de páginas aún no tienen revisión humana. Los cinco casos conservan estado `candidate`.

Cambiar el extractor o la limpieza cambia `extraction_version` y exige regenerar fragmentos, hashes y embeddings. Antes de indexar, revisar manualmente citas, ecuaciones y tablas de cada página y registrar quién aprobó el documento.
