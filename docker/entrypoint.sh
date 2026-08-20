#!/bin/sh
set -e

echo "Aguardando o banco de dados ($DB_HOST:$DB_PORT)..."
until python -c "
import socket, os, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect((os.environ['DB_HOST'], int(os.environ['DB_PORT'])))
except OSError:
    sys.exit(1)
"; do
  sleep 1
done
echo "Banco disponível."

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
