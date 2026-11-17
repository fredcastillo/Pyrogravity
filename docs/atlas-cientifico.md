# Atlas científico de Pyrogravity

## Explorar y citar un estudio

La portada enlaza las fichas de [BASS-II](https://pyrogravity.iclexi.tech/estudios/bass-ii), [FLEX](https://pyrogravity.iclexi.tech/estudios/flex), [Flame Design](https://pyrogravity.iclexi.tech/estudios/flame-design), [CFI-G](https://pyrogravity.iclexi.tech/estudios/cfi-g) y [SPICE](https://pyrogravity.iclexi.tech/estudios/spice). Cada ficha presenta las mediciones publicadas, el método y el registro PSI de NASA.

1. Elige la configuración o cohorte y, si corresponde, el grupo. El enlace conserva la selección en `cohorte` y `grupo`.
2. Usa **Elegir columnas** para ver las variables que necesitas. Abre el número de fila para consultar los demás campos y alertas. El catálogo de tablas NASA también permite elegir columnas y abrir el detalle de un registro.
3. Descarga el CSV filtrado o la gráfica SVG. El CSV exportado conserva la fila de origen, los decimales, la ruta del archivo fuente, su SHA-256, el registro de NASA, la selección y la versión del método. Es una exportación de las filas del análisis y su huella identifica el CSV original de NASA.
4. Cita el estudio, la fuente y la configuración utilizada. Las comparaciones son descriptivas. Los rótulos en español mantienen las unidades y el JSON de la ficha conserva las claves y los criterios originales.

## Consultas y evidencia

La burbuja de chat aparece en la portada, las fichas y el Atlas. El botón **Consultar fuentes** abre la misma conversación. Puedes empezar con un saludo, pedir el catálogo o preguntar por la combustión en microgravedad. El menú **Estudio** fija el alcance de los seguimientos, como «¿Cómo hicieron el experimento?». Una mención explícita de otro estudio actualiza la selección. La conversación se conserva en esa pestaña y **Nueva conversación** la reinicia.

BASS-II y FLEX aceptan preguntas documentales. La interfaz añade el estudio cuando falta y acepta citas resueltas de la fuente correspondiente. Los resúmenes editoriales en español solo se muestran cuando coinciden la fuente, la página y el contenido del pasaje revisado. La cita literal se conserva para comprobarlo. Para pasajes sin resumen editorial se presenta el original. Si falta evidencia, el chat pide un estudio, ensayo o variable más precisa.

Flame Design, CFI-G y SPICE tienen una consulta guiada que responde con el método, los resultados y la fuente de la ficha. La disponibilidad de preguntas documentales depende de incorporar sus publicaciones revisadas a la biblioteca.

## Visualizaciones

**Líneas por fila** conecta las mediciones observadas en el orden del CSV. El eje horizontal muestra números de fila y los intervalos pueden contener registros excluidos. **Relación entre variables** muestra las dos mediciones emparejadas como puntos. En una ficha puedes mover **Inspeccionar punto** con el teclado para leer el valor exacto. La descarga SVG conserva el modo seleccionado.

El desplazamiento suave y las animaciones de botones, secciones y gráficas respetan la preferencia de movimiento reducido del dispositivo.

## Implementación y verificación

- `frontend/src/pages/StudyDetail.tsx` consume `GET /api/v1/analyses/{id}`. `frontend/src/studies.ts` mantiene los nombres de las variables, las notas metodológicas y la exportación. Los criterios científicos y las mediciones se generan desde el catálogo existente.
- CloudFront sirve el mismo índice publicado para `/estudios/{id}` mediante la función `infrastructure/aws/redirect_legacy_home.js`. La ruta de desarrollo en `infrastructure/demo/app.py` aplica el mismo contrato. El Atlas general conserva su enlace a los recursos de la publicación activa.
- El fondo estático se muestra desde la primera pintura. El fondo 3D se inicia después de la carga en equipos con puntero preciso y anchura suficiente. Respeta la preferencia de movimiento reducido.
- Para reproducir el build, ejecuta `npm ci`, `npm test` y `npm run build -- --base ./` desde `frontend/`. Para la compilación publicada, define `VITE_STATIC_HOST=true` y `VITE_AI_DEMO_MODE=false`.
- El CI ejecuta `python infrastructure/aws/browser_smoke.py URL --command-center` con Playwright. Verifica cinco fichas, rutas, fuentes, visualización móvil, selección persistente, descargas y navegación entre el Atlas y la portada. La verificación pública usa el mismo commit en la web y en la API.
