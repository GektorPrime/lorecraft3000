# LoreCraft3000 frontend

React + TypeScript + Vite frontend for LoreCraft3000, talking to the FastAPI
backend's typed `/api/v1` JSON API. See the root [README.md](../README.md), "Frontend"
section, for setup, running in development, production build, and test
instructions.

Quick reference:

```bash
npm install       # install dependencies
npm run dev       # dev server with hot reload (proxies /api to the backend)
npm run build     # production build -> dist/ (served by FastAPI, see app/main.py)
npm test          # vitest + @testing-library/react
```
