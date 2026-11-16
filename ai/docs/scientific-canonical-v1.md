# Canonicalización científica v1.1

Reglas `scientific-result-c14n-v1` y `scientific-input-set-c14n-v1`. Son parte del borrador v1.1; cambiarlas exige otro identificador de versión. El código de referencia está en `src/pyrogravity_ai/schemas/scientific_canonical.py`. Los ejemplos sintéticos de `contracts/v1_1/ScientificResult.example.json` y `ScientificInputSet.example.json` son vectores de prueba entre equipos.

## `ScientificResult.data_version`

1. Validar el objeto `ScientificResult` y construir su JSON con todos los campos del contrato, incluso los `null` explícitos. `canonicalization_version` debe ser `scientific-result-c14n-v1`.
2. Excluir **solo** `result_id`, `data_version`, `source` y `datasets[].database_dataset_id` del contenido usado para el hash. El ID numérico permanece en el objeto transmitido. Otro campo exclusivo del motor de almacenamiento requerirá una regla nueva; no se excluye por inferencia.
3. Ordenar `datasets[]` por `ref_id` y `data[]` por `datum_id`. Ordenar `dataset_ref_ids[]` de cada derivado; conservar el orden de `input_cells[]`, pues puede representar una operación dirigida como final menos inicial. Los demás arreglos conservan su orden y deben ser emitidos de forma determinista por el adaptador.
4. Normalizar solo `data[].value`: `Decimal` finito convertido a cadena decimal sin exponente, ceros fraccionarios innecesarios ni signo de cero negativo. Conservar literalmente `raw_value`, cabeceras, títulos, rutas y otras cadenas de procedencia. Los valores `null` restantes siguen presentes.
5. Serializar JSON UTF-8 con claves ordenadas, `ensure_ascii=False`, separadores `,` y `:`, sin espacios de formato ni valores NaN. `data_version = SHA-256` hexadecimal minúsculo de esos bytes. El identificador de regla forma parte del JSON usado para el hash.

`dataset_ref_id` se calcula como `ds_` más los primeros 48 caracteres hexadecimales del SHA-256 del JSON canónico `{"psi_code": ..., "relative_path": ..., "sha256": ...}`. La ruta es la POSIX relativa del manifiesto científico; el ID PostgreSQL no participa. `trial_code` mantiene `{psi_code}:{table_name}:{source_record}`, con `source_record` desde 1 después de la cabecera.

## `DerivedDatum.input_set_sha256`

El hash de entradas agregadas se guarda en el campo existente `input_set_sha256`; `input_set_version` debe ser `scientific-input-set-c14n-v1`. Cada **celda incluida** se representa con exactamente estos campos: `psi_code`, `relative_path`, `dataset_sha256`, `dataset_ref_id`, `source_record`, `column_ordinal`, `source_header`, `variable_code`, `value`, `raw_value`, `unit`, `interpretation_status`. `value` se normaliza como arriba; `raw_value` y `source_header` son literales del CSV. No se incluyen celdas excluidas.

Rechazar celdas duplicadas. Ordenar las entradas por `(psi_code, relative_path, dataset_sha256, source_record, column_ordinal)` y calcular SHA-256 del JSON canónico `{"canonicalization_version":"scientific-input-set-c14n-v1","inputs":[...]}`. `sample_count` es la cantidad efectiva de observaciones utilizadas según el método, no el número de celdas; el adaptador debe comprobarlo. Para operaciones puntuales se usan `input_cells[]` en el orden de la operación; un delta lleva dos celdas y `sample_count=1`. El hash identifica entradas, pero su verificación requiere conservar o reconstruir esas celdas en Scientific Catalog.

`validated` requiere procedencia, decimal finito, interpretación `exact`, unidad conocida y reglas de inclusión del análisis. En derivados exige método, versión, muestra efectiva y entradas verificables. Advertencias y limitaciones permanecen en el resultado. La matriz específica de inclusión de cada uno de los cinco análisis pertenece al adaptador de Stanley; ninguna cifra se promueve a `validated` por la sola presencia de un hash.
