#!/bin/bash
# system_health.command — Double-click in Finder to run system health check.
# Canonical location: ~/Downloads/Claude Memory/launchers/system_health.command
# Created: 2026-07-27
exec /usr/bin/python3 "$(dirname "$0")/system_health.py"
