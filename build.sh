#!/usr/bin/env bash
# Exit on error
set -e

echo "=== Step 1: Building React/Vite Frontend ==="
cd frontend
npm ci || npm install
npm run build
cd ..

echo "=== Step 2: Installing Python Dependencies ==="
pip install --upgrade pip
pip install -r backend/requirements.txt

echo "=== Step 3: Preparing Storage Directory ==="
mkdir -p storage/masks

echo "=== Build Finished Successfully ==="
