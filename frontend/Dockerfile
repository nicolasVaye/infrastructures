# Frontend: NiceGUI app — pure REST client of the backend (stateless).
FROM zauberzeug/nicegui:latest

# Pin the NiceGUI version actually shipped in the image: reproducible builds.
# The base image is `latest`, so its bundled version floats — this pip install
# is what really decides the version at runtime. Bump the pin here AND in
# frontend/pyproject.toml together (>=3.12.0 also covers the Dependabot
# advisories: restructured_text file read, upload filename sanitization,
# /_nicegui/ static-route log amplification).
RUN pip install --upgrade python-engineio python-socketio "nicegui[highcharts]==3.18.0"

WORKDIR /app

# Shared package (DTOs + API clients): install the source tree directly
# alongside the app so `import shared` works without any build backend.
COPY shared/src/shared/ /app/shared/

COPY frontend/app/ /app/

EXPOSE 8080

# STORAGE_SECRET is required for signed browser sessions.
# BACKEND_URL points to the FastAPI service (docker-compose network name).
CMD ["python", "main.py"]
