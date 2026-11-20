#!/bin/bash
echo "==> Memulai Build Pelaporan Bulanan..."
python3 -m pip install --break-system-packages -r requirements.txt 2>/dev/null || true
python3 manage.py collectstatic --noinput 2>/dev/null || true
echo "==> Build Selesai."
