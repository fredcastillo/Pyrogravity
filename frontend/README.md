# Pyrogravity Frontend

Primer incremento del Command Center científico. Incluye navegación, galaxia 3D interactiva, explorador, comparación, fuentes, estado y un modo snapshot local para que la demo no dependa de servicios externos.

## Desarrollo

```bash
npm ci
npm run dev
```

## Verificación

```bash
npm run lint
npm test
npm run build
```

Los datos visibles son un snapshot de demostración basado en las investigaciones listadas por el proyecto. Las series están normalizadas para navegación y no deben interpretarse como una simulación física validada. La integración definitiva consumirá contratos versionados de FastAPI y ChartSpec.

## Contrato de consultas IA

El contrato versionado vive en `src/contracts/ai.ts`. El frontend envía `AiQueryRequest 1.0` y exige una respuesta `AiResponse 1.0` con el mismo `request_id`. La interfaz representa explícitamente:

- estados `supported`, `partially_supported`, `insufficient_evidence`, `invalid_request` y `upstream_unavailable`;
- afirmaciones enlazadas a `evidence_ids`;
- citas documentales con fuente y página;
- citas científicas con dataset, variable, medición y unidad;
- limitaciones generales y específicas de cada `ChartSpec`;
- latencia, intención y versión del contrato.

Para conectar FastAPI, define la URL completa del endpoint de consultas:

```bash
VITE_AI_QUERY_ENDPOINT=https://api.example.org/v1/ai/query
```

Sin esa variable se usa un adaptador local de demostración. Los `ChartSpec` nunca incorporan datos arbitrarios: `data_ref` se muestra bloqueado y el navegador no lo consulta hasta que backend defina el endpoint autorizado de datos de gráficos.
