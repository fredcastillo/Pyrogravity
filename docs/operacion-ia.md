# Integración privada de Pyrogravity AI

## Estado de la integración

La pila `pyrogravity-ai-private` aprovisiona el motor en Lambda y su bucket
privado. La API pública usa `lambda:InvokeFunction` sobre HTTPS firmado por AWS
con el rol de ejecución del backend. La función privada carece de URL pública.
El transporte HTTP con bearer token continúa disponible para otros entornos.

### Activación del proveedor en AWS

En Secrets Manager de `us-east-1`, los tres secretos se editan como objetos JSON.
Usa un login PostgreSQL separado para cada capacidad y DSN con TLS verificado.

| Secreto | Claves |
| --- | --- |
| `pyrogravity-ai-private/runtime` | `COHERE_API_KEY`, `COHERE_MODEL`, `AI_DATABASE_URL` del login miembro de `pyrogravity_ai_runtime`. Opcionales: `COHERE_TIMEOUT_SECONDS` (8), `COHERE_MAX_RETRIES` (0), `AI_DB_CONNECT_TIMEOUT_SECONDS` (4). |
| `pyrogravity-ai-private/backend` | `AI_CITATION_VIEW_DATABASE_URL` del login miembro de `pyrogravity_ai_citation_reader`. `PYROGRAVITY_DATABASE_URL` se reserva para el lector científico. |
| `pyrogravity-ai-private/ingest` | `AI_INGEST_DATABASE_URL` del login miembro de `pyrogravity_ai_ingest` y la clave de embeddings `COHERE_API_KEY`. |

El operador de ingesta asume el rol indicado por `IngestRoleArn` y utiliza
`pdf/<sha256>.pdf` en el bucket `CorpusBucket`. Las identidades de runtime e
ingesta pueden leer los PDF. El backend tiene lectura de su propio secreto e
invocación de Lambda. Antes de habilitar la IA pública, verifica permisos de los
logins, carga y revisa los pasajes, y sella y activa la generación.

Para habilitar el proveedor, aplica la plantilla de la demo con
`PrivateAiFunctionArn` y `BackendAiSecretArn` de la pila privada. Espera la
actualización del alias y prueba el contrato desde la URL pública. Ambos
parámetros vacíos vuelven al modo de demostración. Las actualizaciones
automáticas conservan los parámetros aprobados. Los valores de los secretos no
se entregan a GitHub Actions.

`main` todavía precede al módulo `ai/`. La suite obligatoria entra en el gate en cuanto el checkout contiene el módulo, una migración de IA o el adaptador `ScientificResult`. Se verifica en una rama de prueba que combina los PR del equipo. La demo pública actual sigue su flujo de publicación independiente. [PR de AI #33](https://github.com/fredcastillo/Pyrogravity/pull/33) · [Contrato backend #35](https://github.com/fredcastillo/Pyrogravity/pull/35)

La documentación de Johan registra `20261115120000` como aplicada en Supabase. La comprobación de esta sesión cubrió GitHub y el entorno desechable. No había conexión autorizada al PostgreSQL remoto ni sesión vinculada de Supabase CLI. En AWS, la consulta de nombres encontró los buckets de la demo y no encontró secretos con prefijo `pyrogravity` en Secrets Manager de `us-east-1`.

## Dos bases desechables en CI

- **IA** usa el servicio local `pyrogravity_ai_test`, con PostgreSQL 17 y pgvector 0.8.2. La suite crea `extensions`, habilita `vector` en el esquema y prepara `anon`, `authenticated` y `service_role` como roles de prueba `NOLOGIN`. Comprueba las tres migraciones en orden y la propuesta de permisos dentro de una transacción que se revierte.
- **Datos** usa su propio contenedor PostgreSQL. `scripts/prepare_ci_postgres.py` configura los prerrequisitos antes de probar la integración científica. Cuando existe `ai/`, se instala en modo editable para poder resolver los JSON Schema versionados del repositorio.
- **Gate** exige que IA termine con éxito cuando está presente. Una conexión desechable ausente, un fallo de importación o un caso omitido hace fallar la suite. Los puertos de los servicios de CI se publican en loopback en runners desechables. La autenticación `trust` es exclusiva de esos servicios efímeros.

## Roles de PostgreSQL propuestos

Los nombres corresponden a grupos `NOLOGIN`. Una vez aprobados, el operador vincula cada grupo a un login distinto, creado y rotado fuera de Git. La conexión de ejecución de cada servicio usa su propio login. El esquema `ai` se mantiene fuera de los esquemas expuestos por la Data API. [SQL de la propuesta](../infrastructure/supabase/proposals/ai_service_roles.sql)

| Capacidad | Rol de grupo propuesto | Permiso que se prueba |
| --- | --- | --- |
| Ingesta | `pyrogravity_ai_ingest` | Inserta fuentes, documentos extraídos, fragmentos, embeddings, jobs y borradores de generación. Lee los campos necesarios para idempotencia y para el trigger de sellado. La revisión documental, incorporación a una generación, sellado y activación corresponden al operador. |
| Runtime AI | `pyrogravity_ai_runtime` | Lee los campos que necesitan la búsqueda textual y vectorial. RLS limita la lectura a la generación activa, documentos revisados y vectores con la configuración activa. |
| Backend | `pyrogravity_ai_citation_reader` | `USAGE` en `ai` y `SELECT` en `ai.citation_passages`. La vista filtra evidencia por revisión, pertenencia a la generación activa y configuración del embedding. |

La validación usa `SET LOCAL ROLE` con cada grupo. También prueba que los roles Data API, incluido `service_role`, carecen de acceso a pasajes, documentos y vectores. Los roles de servicio carecen de `BYPASSRLS`, creación de roles y base, y propiedad de los objetos. La vista usa la identidad de su dueño para acceder a sus tablas base. Conservar el filtro de la vista es parte del límite de acceso del backend. [RLS y vistas en Supabase](https://supabase.com/docs/guides/database/postgres/row-level-security)

## Backend ↔ AI

Los PR conservan `POST /internal/v1/ai/query` y `Authorization: Bearer`. AI rechaza un token ausente o incorrecto con `401`. Los timeouts se propagan como `504` en el servicio interno y quedan clasificados como `timeout` por el cliente de Gregori. El cliente clasifica una conexión caída o un `503` como `upstream_unavailable`. El navegador usa la ruta pública del backend.

Propuesta para AWS: AI escucha dentro de una red privada con TLS y acceso de red desde el backend. Cada tarea o servicio obtiene del gestor de secretos únicamente las referencias que consume. Michael y Gregori deben confirmar el entorno, los roles de ejecución y el mecanismo de inyección antes de activarlo.

| Identidad | Variables | Configuración |
| --- | --- | --- |
| Runtime AI | `AI_INTERNAL_TOKEN`, `AI_DATABASE_URL`, `COHERE_API_KEY` | Token compartido de ≥32 caracteres y login del runtime. |
| Backend | `AI_INTERNAL_TOKEN`, `AI_CITATION_VIEW_DATABASE_URL`, `AI_INTERNAL_URL`, `AI_PROVIDER_ENABLED` | Inyección independiente del mismo valor de token, login lector de citas y URL privada HTTPS. Activar el proveedor después del smoke autenticado. |
| Ingesta | `AI_INGEST_DATABASE_URL`, `COHERE_API_KEY` | Login de ingesta y acceso de la tarea de ingesta a los objetos autorizados. |

Separar en Secrets Manager el token interno y los DSN de cada servicio. Conceder `secretsmanager:GetSecretValue` sobre cada ARN necesario al rol que lo usa. Configurar `sslmode=verify-full` con la CA correspondiente a la conexión PostgreSQL. Para rotar el token actual de un solo valor, preparar la versión nueva, actualizar ambos servicios en una ventana coordinada, probar la llamada autenticada y confirmar que el token anterior obtiene `401`. Mantener encabezados de autenticación y DSN fuera de logs y del bundle web. [Buenas prácticas de Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)

## PDFs privados

El destino oficial sigue pendiente de confirmación. Si el equipo elige S3, usar la [plantilla propuesta](../infrastructure/aws/proposals/ai-private-pdfs.yaml) con los dos ARN IAM aprobados. Configura bloqueo público, TLS, cifrado y versionado. Solo el rol de ingesta puede escribir. La lectura de objetos queda limitada a los roles de ingesta y runtime AI. El backend utiliza la vista de citas.

Guardar la clave del objeto como `pdf/<sha256>.pdf` y usar un perfil o rol temporal de ingesta para recuperarlo. Verificar el hash antes de extraer y guardar en `storage_path` la clave estable, sin URL firmada. El cargador actual recupera la fuente NTRS declarada y comprueba su hash. Leer desde el destino privado elegido requiere cablear el lector del corpus en el entorno de ingesta. Confirmar que un GET anónimo y uno con el rol del backend obtienen denegación y que la tarea de ingesta descarga el hash esperado. [Bloqueo público de S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)

Si el equipo elige Supabase Storage, usar un bucket privado independiente para el corpus y autorizar la descarga autenticada únicamente a la identidad de AI con la política específica del bucket y prefijo. Las credenciales de descarga pertenecen a la ingesta o al runtime según su uso. Los objetos y sus políticas se validan después de elegir el servicio. [Buckets privados de Supabase](https://supabase.com/docs/guides/storage/buckets/fundamentals)

## Paso a Supabase

1. Johan confirma con una sesión autorizada y vinculada el historial con `supabase migration list --linked`. Comprueba también la disponibilidad de `extensions.vector` y la presencia de la vista por lectura. Registra solo versiones y estados.
2. Integra el PR #33 y conserva la copia exacta de `20261115120000_ai_initial.sql` en la cadena compartida. Las dos migraciones candidatas de `ai/migrations/` son `20261115123000_ai_kb_generations.sql` y `20261115124500_ai_citation_passages.sql`. Promoverlas con los mismos bytes a `supabase/migrations/` tras revisión.
3. Aprueba los nombres y permisos con Johan, Gregori y Michael. Añade la propuesta de roles como migración posterior independiente. Los logins y la rotación se gestionan fuera del SQL versionado. Conserva la aprobación humana del corpus.
4. Prueba toda la cadena en CI y en el entorno de pruebas del equipo. Revisa el plan mediante `supabase db push --dry-run --linked` sobre el proyecto correcto. Si el historial remoto difiere del plan, resuelve esa diferencia con el operador antes de aplicar. El operador despliega las versiones pendientes con `supabase db push --linked` tras la fusión y confirma el registro con `supabase migration list --linked`.
5. Ejecuta smoke con cada login y verifica que una cita autorizada llega a la UI. Primero se confirma el acceso privado y el contenido revisado. Después se activa una generación sellada y el flujo del proveedor real.

Comprobación de solo lectura para el operador:

```sql
SELECT version FROM supabase_migrations.schema_migrations
WHERE version IN ('20261115120000', '20261115123000', '20261115124500')
ORDER BY version;

SELECT to_regtype('extensions.vector') IS NOT NULL AS vector_disponible,
       to_regclass('ai.kb_generations') IS NOT NULL AS generaciones_disponibles,
       to_regclass('ai.citation_passages') IS NOT NULL AS vista_disponible;
```

[Flujo de migraciones de Supabase](https://supabase.com/docs/guides/deployment/database-migrations)
