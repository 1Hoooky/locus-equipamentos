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

# Bootstrap opcional do primeiro Administrador, só para plataformas sem
# Shell/SSH nem execução avulsa de comando (Render Free — ver
# docs/deploy-render-neon.md). Sem efeito nenhum aqui no VPS: só age se
# BOOTSTRAP_ADMIN_USERNAME/PASSWORD estiverem definidas no ambiente, e
# elas nunca são definidas no .env do VPS (o primeiro admin do VPS
# continua sendo criado com `docker compose exec web python manage.py
# createsuperuser`, docs/deploy-fase1.md, seção 10). Ver
# apps/accounts/management/commands/bootstrap_admin.py para as garantias
# de segurança (idempotente, nunca promove usuário existente, sem
# credencial hardcoded, sem endpoint HTTP).
python manage.py bootstrap_admin

python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
