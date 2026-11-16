# Entorno local de Pyrogravity

## Arrancar la demo

Instala Docker con el plugin Compose y arranca el motor de contenedores Linux. Desde la raíz del repositorio:

```sh
docker compose config --quiet
docker compose up --build --wait
```

La [interfaz Command Center](http://127.0.0.1:8080/) sirve la SPA de `frontend/`. nginx dirige `/health` y `/api/v1/` al servicio interno `api:8000`. También puedes abrir la [documentación de FastAPI](http://127.0.0.1:8000/docs) directamente. El Dockerfile genera Parquet desde los CSV del repositorio, con Python 3.12 y sin depender de los archivos procesados del equipo.

La [API de análisis](http://127.0.0.1:8080/api/v1/analyses) expone BASS-II, FLEX, Flame Design, CFI-G y SPICE. El modo demo de la vista IA usa respuestas de interfaz etiquetadas como sintéticas. Los resultados científicos de la API usan los archivos procesados del ETL. La conexión de las vistas de IA al contrato público se sigue en los PR [#33](https://github.com/fredcastillo/Pyrogravity/pull/33), [#34](https://github.com/fredcastillo/Pyrogravity/pull/34) y [#35](https://github.com/fredcastillo/Pyrogravity/pull/35).

## Probar las lecturas desde PostgreSQL

Copia `.env.example` a `.env` y establece `PYRO_DEV_DB_PASSWORD`, `PYRO_DEV_LOADER_PASSWORD` y `PYRO_DEV_READER_PASSWORD`. Usa tres secretos hexadecimales independientes. Puedes generar cada uno con `python -c "import secrets; print(secrets.token_hex(24))"`. Conserva `.env` fuera de Git.

```sh
docker compose -f docker-compose.yml -f compose.postgres.yml config --quiet
docker compose -f docker-compose.yml -f compose.postgres.yml up --build --wait
python infrastructure/local/smoke.py real
```

En un volumen nuevo, PostgreSQL 17 inicia con pgvector, crea los roles de desarrollo y aplica `supabase/migrations/`. El servicio de carga valida el manifiesto y luego escribe con `pyrogravity_nasa_loader`. FastAPI espera su salida satisfactoria y consulta con `pyrogravity_api_reader`. `db` y el cargador permanecen en la red privada de Compose. Este recorrido usa los CSV versionados y una base local.

`/health` debe devolver `mode: real` y `scientific_database: ok`. Los cinco endpoints de detalle deben devolver `source: postgres`. El volumen conserva los datos al detener el proyecto. Los scripts de inicialización de PostgreSQL se ejecutan al crear el volumen. Para ensayar migraciones posteriores desde cero en otra base local, usa otro nombre de proyecto con `-p` y detén primero el proyecto anterior para liberar los puertos.

## Diagnóstico y recuperación

```sh
docker compose ps -a
docker compose logs --tail 100 api web
python infrastructure/local/smoke.py demo
docker compose down
```

En modo PostgreSQL, conserva ambos parámetros `-f` para los comandos de diagnóstico o detención:

```sh
docker compose -f docker-compose.yml -f compose.postgres.yml ps -a
docker compose -f docker-compose.yml -f compose.postgres.yml logs --tail 100 db data-load api
docker compose -f docker-compose.yml -f compose.postgres.yml down
```

Después de detener el modo PostgreSQL, el comando de arranque de la demo vuelve a usar Parquet. Si falla la carga, revisa `data-load` y el manifiesto antes de reiniciar. Evita compartir la salida sin filtrar de `docker compose config`, que interpola contraseñas locales.

## Puntos de entrada por integrante

| Área | Punto de entrada y comprobación |
|---|---|
| Datos · Stanley | `python -m data.src.etl.nasa_etl`, `python -m scripts.load_to_supabase --dry-run` y `python -m pytest data/tests` en Python 3.12. |
| IA · Johan | En el PR #33, `python -m pip install -r requirements.txt` y `python -m pytest tests -ra` desde `ai/`. El motor con proveedor real requiere un corpus aprobado, acceso al esquema `ai` y credenciales propias de desarrollo. |
| API · Gregori | `/docs`, `/health` y `/api/v1/analyses`. El modo PostgreSQL permite comprobar permisos, carga y procedencia con datos de prueba locales. |
| Interfaz · Bryant | `npm ci`, `npm run lint`, `npm test` y `npm run build` desde `frontend/`. La SPA local usa la misma URL de origen que la API. |
| QA · Fred | Ejecuta `python -m pytest tests data/tests infrastructure/aws/tests`. Para RLS y migraciones usa PostgreSQL desechable y la suite de integración de CI. |
| Operación · Michael | Valida Compose, revisa `ci.yml`, `deploy-aws-demo.yml` y `sync-demo.yml`. Los contenedores locales no intervienen en el despliegue Lambda/CloudFront. |
