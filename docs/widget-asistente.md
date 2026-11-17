# Widget del asistente científico

Actualizado: 2026-11-17. Base revisada: `origin/main` en `32d4b31`, merge del PR #55 (chat científico global y gráficas de líneas).

## Personalización

- Conserva las superficies oscuras y los acentos azules del Atlas. Usa la llama existente en el lanzador, encabezado, bienvenida y respuestas.
- La bienvenida ofrece explorar los datos o aprender a verificar la evidencia. Los saludos y las guías de navegación se resuelven localmente; las consultas documentales siguen usando `POST /api/v1/ai/query`.
- Conserva el estudio seleccionado para preguntas de ese estudio. Las preguntas conceptuales generales dejan de heredar el filtro seleccionado y se envían a la búsqueda documental sin alcance de estudio.
- La metodología del chat responde con el método de análisis que Pyrogravity publica en la ficha y aclara que no equivale necesariamente al protocolo experimental NASA. Si falta información en la ficha, indica qué sí puede consultar y enlaza la fuente.
- Muestra el texto de respuesta recibido del backend. No lo sustituye por un resumen elegido solo por documento y página, porque esa coincidencia no demuestra que el resumen responda a la pregunta.
- Ofrece ayuda para interpretar evidencia insuficiente y revisar fuentes, sin generar nuevas afirmaciones científicas en esas guías.
- Permite copiar una respuesta con sus citas y aviso de IA, detener una consulta y reiniciar la conversación. Una respuesta tardía de una consulta cancelada se ignora.
- Muestra citas desplegables y las limitaciones que devuelve el backend. El aviso permanente dice: «Estás hablando con una IA. Puede cometer errores. Verifica los datos y las fuentes antes de usar sus respuestas».

## Comprobaciones

En el commit inicial `88c34f6`: lint, 22 pruebas de frontend y build aprobados. Incluye pruebas de navegación conversacional, copia con aviso y cancelación. Se corrigió una comprobación anterior que podía confundir el número 812 con una subcadena aleatoria de un UUID.

Después se corrigieron tres desvíos detectados visualmente: respuestas conceptuales que heredaban un estudio seleccionado, la pregunta «¿Cuál es la metodología de SPICE?» que no reconocía su intención y respuestas sustituidas por un resumen de página sin comprobar su pertinencia. Estas correcciones aún no se han validado con pruebas locales.

Revisión visual local en escritorio y 390 px móvil. Captura: `widget-asistente-preview.jpg`. La compilación conserva el aviso previo por el tamaño del chunk de Three.js.

No se verificó el proveedor de IA desplegado ni se modificó el contrato HTTP. El servidor local de frontend no incluye el catálogo estático del Atlas ni su backend: esos recursos corresponden a la publicación integrada.
