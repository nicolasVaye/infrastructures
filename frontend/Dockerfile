# Frontend: NiceGUI app — pure REST client of the backend (stateless).
FROM zauberzeug/nicegui:latest

RUN pip install --upgrade python-engineio python-socketio

WORKDIR /app

# Shared package (DTOs + API clients): install the source tree directly
# alongside the app so `import shared` works without any build backend.
COPY shared/src/shared/ /app/shared/

COPY frontend/app/ /app/

EXPOSE 8080

# STORAGE_SECRET is required for signed browser sessions.
# BACKEND_URL points to the FastAPI service (docker-compose network name).
CMD ["python", "main.py"]
