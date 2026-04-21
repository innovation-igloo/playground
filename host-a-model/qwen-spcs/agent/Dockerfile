# ----- Stage 1: Build the React UI -----
FROM node:20-slim AS ui-build

WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build
# Output: /ui/dist

# ----- Stage 2: Python runtime with UI baked in -----
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY agent/ agent/
COPY server/ server/
COPY --from=ui-build /ui/dist ui-dist/
# config.yaml is mounted at runtime from @AGENT_STAGE, NOT baked in.

EXPOSE 8080

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8080"]
