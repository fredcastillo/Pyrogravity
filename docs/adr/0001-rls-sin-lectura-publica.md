# ADR 0001 - RLS sin lectura pública

El frontend accede solo a través de FastAPI con service role. Se habilita RLS en todas las tablas sin políticas para anon/authenticated. La service role ignora RLS. Evita exposición directa de datos científicos.
