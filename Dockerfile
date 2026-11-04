# One image: builds the React app, then serves it and the API from a single FastAPI process.
# Build context is the repository root. Needs VITE_CLERK_PUBLISHABLE_KEY at build time.
FROM node:22-alpine AS web
WORKDIR /w
COPY udyam/frontend/package*.json ./
RUN npm ci
COPY udyam/frontend/ ./
ARG VITE_CLERK_PUBLISHABLE_KEY
ENV VITE_CLERK_PUBLISHABLE_KEY=$VITE_CLERK_PUBLISHABLE_KEY
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* && useradd -m -u 10001 app
# the same directory layout as the repository, so path defaults in app/config.py resolve
WORKDIR /app/udyam/backend
COPY udyam/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY udyam/backend/app ./app
COPY udyam/backend/alembic.ini ./
COPY udyam/backend/alembic ./alembic
COPY --from=web /w/dist /app/udyam/frontend/dist
COPY YTL_TrackA_Udyam_Digital_Data/*.csv /app/YTL_TrackA_Udyam_Digital_Data/
RUN chown -R app /app
USER app
ENV PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000
# Postgres schema is managed by migrations; they run before the server starts.
CMD ["sh", "-c", "if echo \"$DATABASE_URL\" | grep -q '^postgres'; then alembic upgrade head; fi && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
