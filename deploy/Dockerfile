# ---------------------------------------------------------------------------
# Stage 1: build the React frontend
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

# uv is the chosen package manager (matches pyproject.toml)
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install Python deps. README.md is referenced by pyproject.toml, so it must
# be present at build time.
COPY pyproject.toml uv.lock* README.md ./
COPY backend/ ./backend/
RUN uv sync --frozen --no-dev || uv sync --no-dev

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Recordings directory must exist (volume mount target)
RUN mkdir -p /app/recordings

EXPOSE 8000

# Use uv to run uvicorn so we get the project venv on PATH
CMD ["uv", "run", "--no-dev", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
