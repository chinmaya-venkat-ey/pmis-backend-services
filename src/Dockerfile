# pmis-project-service — production image.
#
# Self-contained: no external build context, no sibling-folder copy.
# Build context is just this folder.

FROM python:3.11-slim

# System deps:
# - libpq-dev: for psycopg2 (Postgres adapter)
# - gcc + libffi-dev: for argon2-cffi's C extension (used for password
#   verify on the rare project-service path that needs it; mirrors the
#   user-service base image so the two services share build assumptions)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps. Cached as a separate layer so code-only edits
# don't trigger a re-install.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy service source as the LAST step so code-only edits invalidate
# only this thin layer.
COPY app /app/app
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

# Flush stdout/stderr immediately — better for container logs.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8003

# Bind to 0.0.0.0 so the port is reachable from outside the container.
# No --reload in prod.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
