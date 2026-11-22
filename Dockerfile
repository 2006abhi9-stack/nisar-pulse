# =====================================================================
# NISAR-Pulse Multi-Stage Production Dockerfile for Render Deployment
# =====================================================================

# --- Stage 1: Build Frontend Single Page Application ---
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci || npm install

COPY frontend/ ./
RUN npm run build

# --- Stage 2: Production Python Backend Runtime ---
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies for GDAL, OpenCV, rasterio, and compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgdal-dev \
    gdal-bin \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r ./backend/requirements.txt

# Copy backend application code
COPY backend/ ./backend/

# Copy compiled frontend distribution from Stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Ensure storage directories exist
RUN mkdir -p /app/storage/masks

# Set production environment variables
ENV PYTHONUNBUFFERED=1 \
    STORAGE_DIR=/app/storage/masks

# Start FastAPI via uvicorn with dynamic port routing assigned by Render
CMD ["sh", "-c", "uvicorn main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-10000}"]
