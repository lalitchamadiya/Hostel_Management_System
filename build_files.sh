#!/usr/bin/env bash
echo "Building Vercel project assets..."
python3 -m pip install --break-system-packages -r requirements.txt
python3 manage.py migrate --no-input || true
python3 manage.py collectstatic --no-input --clear
mkdir -p staticfiles
echo "Build complete."
