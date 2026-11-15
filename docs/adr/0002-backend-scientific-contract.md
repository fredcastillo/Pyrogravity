# Compatibilidad del backend con los datos cient?ficos

El PR #16 usa ahora el esquema `scientific.*` y el manifiesto actual de Stanley.
La ingesta se delega a `data.src.database.nasa_loader`: conserva filas vac?as,
estados de lectura, decimales, encabezados, unidades y hashes. Repetir la carga
verifica una versi?n existente; no la sobrescribe.

El esquema alternativo y el adaptador de cach? de Supabase originales se conservan
como referencias en esta carpeta. No son migraciones activas. No se elimina ni
migra una base externa autom?ticamente. La cach? persistente y el motor RAG
contin?an pendientes de sus contratos; el modo real responde 503 si se pide IA
sin un motor conectado, y la demo declara expl?citamente su car?cter simulado.

## Uso

Desde la ra?z, Python 3.12:

```sh
python -m pip install -r requirements.txt
python -m data.src.etl.nasa_etl
python -m scripts.load_to_supabase --dry-run
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m pytest tests -v
```

`GET /api/v1/analyses` devuelve el cat?logo y
`GET /api/v1/analyses/{analysis_id}` ejecuta el an?lisis oficial. La demo lee
Parquet; `DEMO_MODE=false` exige `PYROGRAVITY_DATABASE_URL` con la identidad
`pyrogravity_api_reader`. La conexi?n impone transacciones de solo lectura y
timeout. La ingesta usa otra conexi?n con `pyrogravity_nasa_loader`. Nunca usar
el lector para ingesta ni una clave service-role en el navegador.

La secuencia activa de migraciones est? exclusivamente en `supabase/migrations/`.
Configurar contrase?as fuera del repositorio. El frontend no recibe credenciales
de base de datos. `/health` comprueba el acceso real al esquema y devuelve 503
si no est? disponible, sin mostrar el DSN.

CI ejecuta PostgreSQL real, carga las 21 tablas, verifica RLS e idempotencia y
compara las cinco respuestas HTTP con los resultados SQL y Parquet. La suite
rechaza una base que ya tenga esquema cient?fico; usar ?nicamente PostgreSQL
desechable mediante `PYRO_TEST_DATABASE_URL`.

Este backend queda preparado para revisi?n de Gregori y Stanley. La demo Lambda
publicada mantiene su snapshot validado y no necesita una base de datos externa.
