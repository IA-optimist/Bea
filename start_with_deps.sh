#!/bin/bash
# Install packages that may not be in the Docker image yet
pip install --quiet sentence-transformers torch --no-deps 2>/dev/null || true
python3 -c 'import sentence_transformers' 2>/dev/null || pip install -q sentence-transformers 2>/dev/null || true
exec python main.py
