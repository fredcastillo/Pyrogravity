# Pyrogravity Frontend

Command Center científico con navegación, cámara 3D, explorador, comparación, fuentes y consultas de evidencia.

## Desarrollo y verificación

```bash
npm ci
npm run dev
npm run lint
npm test
npm run build
```

Los datos generales visibles son un snapshot de navegación y no una simulación física validada.

## Contrato público de IA `public-1.1`

La frontera del navegador está fijada en `src/contracts/ai.ts` y `src/services/ai.ts`:

- única operación: `POST /api/v1/ai/query` en el mismo origen;
- el navegador no llama a Cohere, Supabase ni endpoints internos de IA;
- solicitud con pregunta, ensayos seleccionados, variables y preferencia de gráfico;
- soporte separado en `supported`, `partially_supported` e `insufficient_evidence`;
- errores de servicio representados exclusivamente como errores HTTP y el sobre oficial `error.code/message/request_id/details`;
- respuesta con afirmaciones, citas resueltas, limitaciones, gráficos y `provenance` (`live`, `cache`, `demo`, `degraded`);
- cifras presentadas siempre con unidad y procedencia;
- gráficos renderizados solo cuando el backend entrega series con `validated: true` y puntos hidratados;
- `data_ref` solo admite rutas relativas bajo `/api/v1/`; nunca se consulta una referencia externa.

Los tipos reflejan el contrato `public-1.1` publicado por Gregori en `docs/api/openapi.json`. FLEX usa el identificador canónico publicado `PSI-69:psi-69_flex:1`; las familias que todavía no tienen un ensayo canónico aprobado envían `experiment_ids: []` para obtener evidencia documental o `insufficient_evidence`, nunca un identificador inventado.

En desarrollo, el navegador mantiene la ruta relativa y Vite puede redirigirla hacia FastAPI:

```bash
VITE_API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev
```

## Demostración explícita

El modo demo es opt-in:

```bash
VITE_AI_DEMO_MODE=true npm run dev
```

En demo, la respuesta usa `provenance: demo`, `status: insufficient_evidence`, no contiene citas, mediciones ni gráficos, y la interfaz muestra una advertencia inequívoca. Sin ese modo, el frontend intenta `/api/v1/ai/query`; si el backend no está disponible, muestra un error de servicio.
