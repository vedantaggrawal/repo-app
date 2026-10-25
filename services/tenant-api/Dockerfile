FROM python:3.12-slim

# Pull fixed Debian packages: the floating base tag lags security fixes, and
# CI fails the build on any fixable HIGH/CRITICAL CVE (Trivy).
RUN apt-get update && apt-get -y upgrade && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/tenant-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/tenant-api/main.py services/tenant-api/migrate.py ./

# Migrations ship in the image; the initContainer runs migrate.py as the owner role.
COPY db/migrations /migrations

USER 10001
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
