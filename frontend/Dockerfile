# Frontend: NiceGUI app — pure REST client of the backend (stateless).
FROM zauberzeug/nicegui:latest

# Security: the base image bundles whatever NiceGUI version was current at
# build time. Force at least 3.12.0, which patches:
#   - GHSA: ui.restructured_text() local file read (file_insertion/raw directives)
#   - GHSA-9ffm-fxg3-xrhh bypass: upload filename backslash sanitization
#   - unauthenticated log amplification via /_nicegui/ static asset routes
RUN pip install --upgrade python-engineio python-socketio "nicegui[highcharts]>=3.12.0,<4"

WORKDIR /app

# Shared package (DTOs + API clients): install the source tree directly
# alongside the app so `import shared` works without any build backend.
COPY shared/src/shared/ /app/shared/

COPY frontend/app/ /app/

EXPOSE 8080

# STORAGE_SECRET is required for signed browser sessions.
# BACKEND_URL points to the FastAPI service (docker-compose network name).
CMD ["python", "main.py"]
