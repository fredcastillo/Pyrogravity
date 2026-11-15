# Contratos de integración v1 (propuesta P1)

Estos son los contratos de intercambio para la fase P1. Los modelos Pydantic están en `src/pyrogravity_ai/schemas/contracts.py`; los esquemas JSON y ejemplos en `contracts/v1/` permiten revisión desde backend y frontend sin importar Python. Todos los ejemplos son **sintéticos**: ninguna cifra o fila de ejemplo se presenta como dato NASA.

## Flujo

1. El backend envía `AiQueryRequest` con `request_id` estable. `analysis_id` solo puede elegir uno de los cinco análisis que figuran en el catálogo científico actual; `filters` nunca son SQL y el contrato solo admite `pi` y `material` para `bass-ii`. El adaptador vuelve a comprobar las capacidades del catálogo al ejecutar el análisis.
2. Stanley mantiene `data/src/analysis/scientific_catalog.py`. Su `run_analysis()` devuelve un sobre con `analysis_id`, `psi_code`, `source`, `contract_version`, `filters` y un `result` específico de cada análisis. **No devuelve aún `ScientificResult`**. Un adaptador acordado con Stanley debe transformar solo datos cuya unidad, versión y procedencia se puedan verificar. El resultado normalizado va al orquestador, no al navegador directamente.
3. El motor devuelve `AiResponse`. Cada `Claim` referencia evidencia por ID; `claims[].evidence_ids` junto a `evidence[]` son las citas que puede presentar el frontend. La evidencia documental identifica fuente, hash del PDF, página y hash del chunk; la científica identifica dataset, versión SHA-256, dato, unidad y fila/columna, o método y tamaño de muestra para derivados validados. `supported` exige al menos un claim con evidencia; errores y evidencia insuficiente no llevan claims ni gráficos.
4. `ChartSpec` describe un gráfico, sin incrustar filas ni código. `data_ref` es un identificador opaco para que el backend resuelva los puntos desde un endpoint autorizado. El frontend no debe tratarlo como URL, SQL o ruta local. La línea exige un eje temporal; el eje numérico exige unidad. El backend deberá verificar que campos y filtros coinciden con la serie que entrega.

## Identidades y números

- `psi_code` (por ejemplo `PSI-69`) identifica la investigación; `database_dataset_id` es la clave BIGINT de `scientific.datasets` y puede faltar cuando el origen es Parquet. No son intercambiables.
- La versión del dataset se expresa con `relative_path` y SHA-256 del manifiesto. `source_record` y `column_ordinal` corresponden a la clave de medición de `scientific.measurements`; para un dato derivado se exige método y `sample_count`.
- `ScientificDatum.value` es una cadena decimal finita para no introducir redondeo al convertir JSON a `float`. El frontend puede convertirla para graficar después de validar su unidad y rango. `validation_status` acepta solo `validated`; valores provisionales no entran en este contrato de evidencia.
- `schema_version` fija el formato externo en `1.0`. Cambios incompatibles requieren una versión nueva. Campos desconocidos se rechazan.

## Generación y revisión

Desde la raíz del repositorio, con el entorno de AI activo:

```powershell
python ai/scripts/export_contracts.py
python ai/scripts/export_contracts.py --check
python -m pytest ai/tests/test_contracts.py -q
```

Pendiente de acuerdo con Stanley, Gregori y Bryant: adaptador de las cinco formas de `run_analysis()`, resolución/autorización de `data_ref`, forma del endpoint y mapeo de errores HTTP. El contrato no implementa estas integraciones ni habilita escritura en Supabase. Antes de considerar un resultado real como `validated`, el adaptador debe comprobar versión, unidad, interpretación y trazabilidad frente a los datos de Stanley.
