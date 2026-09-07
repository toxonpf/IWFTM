#!/usr/bin/env bash
cd "$(dirname "$0")"
xdg-open http://127.0.0.1:8765 &>/dev/null &
python3 server.py
