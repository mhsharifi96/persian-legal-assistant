# Docker Compose Contract

## File Set

When adding Docker support, prefer this minimal file set:

```text
Dockerfile
docker-compose.yml
docker-compose.override.yml      # optional local-only override
.dockerignore
.env.example
```

If the repository already has a different convention, follow it unless it violates the project architecture.

## Recommended Service Names

Use stable names:

```yaml
services:
  web:
  worker:
  postgres:
  redis:
  qdrant:
  neo4j:
```

Stable names matter because internal URLs should use service hostnames:

```text
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/persian_legal_assistant
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333
NEO4J_URI=bolt://neo4j:7687
```

## Baseline Compose Shape

Use this as a reference, not a file to paste blindly:

```yaml
services:
  web:
    build:
      context: .
    command: python manage.py runserver 0.0.0.0:8000
    env_file:
      - .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      qdrant:
        condition: service_started
      neo4j:
        condition: service_healthy

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: persian_legal_assistant
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d persian_legal_assistant"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

Add `qdrant`, `neo4j`, `redis`, and `worker` only when needed.

## Dockerfile Baseline

Recommended approach for Python/Django:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home appuser
USER appuser

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

Adjust dependency files for Poetry, uv, pip-tools, or pyproject-based projects.

## .dockerignore Baseline

Ignore at least:

```text
.git
.env
.env.*
!.env.example
.venv
venv
__pycache__
.pytest_cache
.mypy_cache
.ruff_cache
.DS_Store
db.sqlite3
media
staticfiles
models
model_cache
datasets
data/raw
data/interim
data/processed
qdrant_storage
neo4j/data
neo4j/logs
```

## Verification Commands

Run these after Docker changes:

```bash
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 web
```

If Django exists:

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py migrate
```

If pytest exists:

```bash
docker compose exec web pytest
```

## Integration Testing

Use Docker Compose to run integration tests against live Postgres, Qdrant, and Neo4j. Keep these tests marked separately from unit tests so normal development stays fast.

Do not require OpenAI or paid model APIs for the default Docker health path.

