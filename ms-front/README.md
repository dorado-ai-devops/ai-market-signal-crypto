# Market Signal - Frontend

Resumen rápido

Este es el frontend de Market Signal: una SPA React + TypeScript creada con Vite y Tailwind (shadcn/ui). Consume una API FastAPI (backend en `market-signal`) para mostrar estado, señales, items y métricas en tiempo real. Soporta modo mock para desarrollo sin backend.

Variables de entorno

- `VITE_API_BASE` — URL base del backend (ej: `http://localhost:8000`).
- `VITE_USE_MOCK` — `true`|`false`. Habilita datos sintéticos.

Instalación y ejecución

```bash
# instalar dependencias (usa pnpm recomendado, npm/yarn funcionan también)
pnpm install

# desarrollo
pnpm dev

# build
pnpm build

# preview de producción
pnpm preview
```

Arquitectura y flujo

- Build: Vite + React + TypeScript
- UI: Tailwind CSS y componentes de `shadcn/ui` (componentes locales en `src/components/ui`).
- Estado global: Zustand (`src/store/state.ts`).
- Network: Axios con un cliente configurado en `src/api/http.ts` y servicios en `src/api/service.ts`.
- Real-time: SSE (`/api/events`) con fallback a polling.

Endpoints esperados del backend

- `GET /health`
- `GET /api/state`
- `GET /api/signals?limit=...`
- `GET /api/items?limit=...`
- `GET /api/metrics`
- `GET /api/events` (SSE)

Estructura relevante (resumen de archivos)

- `index.html`, `src/main.tsx`, `src/App.tsx` — entrada y proveedor de React Query + routing.
- `src/pages/Dashboard.tsx` — vista principal (KPIs, gráfico de señales, live feed, tabla de items). Punto central de orquestación: carga datos, configura SSE y timers.
- `src/components/` — componentes reutilizables: `KpiCard`, `SignalsChart`, `LiveFeed`, `ItemsTable`, `HealthIndicator`, etc.
- `src/api/service.ts` — wrapper de alto nivel para llamadas REST y apertura de SSE. Soporta modo mock (`src/api/mock.ts`).
- `src/store/state.ts` — Zustand store que guarda state, signals, items, metrics, y acciones para añadir nuevos eventos en tiempo real.
- `src/lib/utils.ts` — utilidades (p.ej. `cn` para clases tailwind).
- `public/` — assets estáticos.

Comportamiento clave

- Dashboard carga datos iniciales (state, signals, items, metrics) y refresca periódicamente.
- Intenta abrir una conexión SSE; si falla, usa polling para refrescar signals/items.
- `SignalsChart` filtra señales por rango (1h/6h/24h) y muestra EMA y mentions en un ComposedChart (Recharts).
- `ItemsTable` ofrece búsqueda, paginación y filtros por fuente.

Desarrollo y testing rápido

- Usa `VITE_USE_MOCK=true` para trabajar sin backend.
- Añade componentes o páginas en `src/components` y `src/pages`.

Notas y recomendaciones

- Las dependencias son numerosas (Radix, Recharts, shadcn/ui). Usa pnpm para instalaciones reproducibles.
- Para integrar con el backend local, arranca `market-signal` y pon `VITE_API_BASE=http://localhost:8000`.
- Considerar añadir tipos más estrictos en `src/types` y tests (Vitest) para componentes críticos.

Siguientes pasos sugeridos

- Añadir script `pnpm lint` y CI básico que corra build y lint.
- Documentar el formato SSE esperado en `README` del backend para asegurar compatibilidad.
- Añadir e2e tests (Playwright) para flujos críticos del dashboard.

---
Archivo generado automáticamente a partir del contenido del repositorio.
# Market Signal Dashboard

Professional operational dashboard for monitoring ETH market signals with real-time data visualization.

## Features

- **Real-time Health Monitoring**: Live health checks with visual indicators
- **KPI Dashboard**: EMA(15m), mentions, baseline metrics with color-coded status
- **Interactive Charts**: Timeline visualization with Recharts, reference lines, and tooltips
- **Live Data Feed**: SSE support with fallback to polling
- **Smart Filtering**: Search and filter items by source, text, and score
- **Professional Dark UI**: Optimized for operational use

## Environment Variables

Create a `.env` file in the root directory:

```env
VITE_API_BASE=http://localhost:8000
VITE_USE_MOCK=false
```

### Configuration Options

- `VITE_API_BASE`: FastAPI backend URL (default: http://localhost:8000)
- `VITE_USE_MOCK`: Use mock data instead of real API (true/false)

## Mock Mode

When `VITE_USE_MOCK=true`, the dashboard uses synthetic data that simulates:
- Health status (always healthy)
- Real-time state updates with EMA calculations
- Signal history with realistic patterns
- News items with varying sentiment scores
- Metrics with random but realistic values

To disable mock mode and connect to your FastAPI backend, set `VITE_USE_MOCK=false`.

## API Endpoints

The dashboard expects these FastAPI endpoints:

- `GET /health` → `{ "ok": boolean }`
- `GET /api/state` → Current market state with EMA, mentions, action
- `GET /api/signals?limit=200` → Historical signals array
- `GET /api/items?limit=100` → Recent news items with sentiment scores
- `GET /api/metrics` → System metrics (totals, averages)
- `GET /api/events` → Server-Sent Events stream (optional)

## Development

```bash
# Install dependencies
pnpm install

# Start development server
pnpm dev

# Build for production
pnpm build

# Preview production build
pnpm preview
```

## Docker

Build the frontend container:

```dockerfile
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN pnpm install
COPY . .
RUN pnpm build
EXPOSE 3000
CMD ["pnpm", "preview", "--host", "0.0.0.0", "--port", "3000"]
```

## Architecture

- **Frontend**: React + TypeScript + Vite
- **UI**: Tailwind CSS + shadcn/ui components
- **Charts**: Recharts for data visualization
- **State**: Zustand for client state management
- **HTTP**: Axios with configurable base URL
- **Real-time**: Server-Sent Events with polling fallback

## Usage

1. Start your FastAPI backend on port 8000
2. Set `VITE_USE_MOCK=false` in `.env`
3. Run `pnpm dev`
4. Dashboard auto-refreshes every 5s (configurable)
5. Use live activity panel to monitor real-time events
6. Click chart points for detailed signal information

The dashboard is optimized for operational use with clear visual indicators, responsive design, and professional dark theme.