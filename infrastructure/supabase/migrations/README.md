La unica secuencia de migraciones activa es `supabase/migrations/` en la raiz.
El esquema alternativo inicial del PR #16 se conserva para referencia en
`docs/adr/0001-proposed-schema.sql.reference`. No debe ejecutarse sobre una base
existente ni sobre el esquema cientifico de Stanley.

El backend consulta `scientific.*` con `pyrogravity_api_reader`; el cargador usa
`pyrogravity_nasa_loader`. Son identidades distintas y sus contrasenas se configuran
fuera de Git. No se requiere una service-role key de Supabase.
