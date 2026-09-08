#!/bin/sh
set -eu

echo "Applying database migrations..."
python manage.py migrate --noinput

case "${SEED_DEMO_ON_START:-true}" in
  1|true|TRUE|yes|YES)
    echo "Loading the idempotent staging demo dataset..."
    python manage.py seed_demo
    ;;
esac

echo "Starting Gunicorn..."
exec gunicorn --config gunicorn.conf.py config.wsgi:application
