# Cómo contribuir a Pyrogravity

1. Abre o toma una tarea en [Issues](https://github.com/fredcastillo/Pyrogravity/issues). Asigna la etiqueta del área e indica cómo se podrá comprobar el resultado. Vincula las tareas de la primera demo al hito **MVP de la demo**.
2. Actualiza tu rama desde main antes de trabajar. Las ramas users/* ya existen. Para tareas independientes puedes crear una rama corta vinculada al issue.
3. Abre un pull request hacia main y adjunta una forma de reproducir la verificación. Avisa al responsable de los módulos que cambien.
4. Si cambias un contrato que otro módulo consume, coordina el cambio con esa persona e incluye el ejemplo JSON actualizado. Para un dato científico, adjunta la fuente, versión, fila o sección y unidad.
5. Revisa el resultado de **Verificación general** y resuelve los fallos antes de fusionar.

## Qué ejecuta CI

| Comprobación | Cuándo se ejecuta |
| --- | --- |
| Workflows | En cada PR hacia main y cada push a main. |
| Docker Compose | Cuando se añade un archivo Compose en la raíz. |
| Python 3.12 | Revisa la sintaxis por módulo cuando encuentra código en data/, rag/, backend/ o tests/. Ejecuta pytest cuando hay pruebas en el módulo. |
| Frontend | Cuando existe frontend/package.json. Usa Node.js 24, instala con npm ci, ejecuta lint y test si están definidos y compila con npm run build. Incluye el package-lock.json con el primer PR del frontend. |

Los módulos Python pueden declarar dependencias con requirements.txt o pyproject.toml, y dependencias de prueba con requirements-dev.txt. Los comandos de pruebas se ejecutan desde su módulo. Mantén las pruebas de CI reproducibles con dobles de servicios o datos de demo.

Para trabajar con datos, conserva el original fuera del árbol versionado y registra su URL y DOI. Sube las muestras pequeñas que necesite la demo con su procedencia. Documenta las variables necesarias en archivos .env.example y guarda los valores en el entorno de cada servicio.
