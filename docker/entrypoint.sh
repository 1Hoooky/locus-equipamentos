#!/bin/sh
set -e

echo "Aguardando o banco de dados..."
# Se DATABASE_URL estiver definida (Render+Neon — ver
# config/settings/render.py e docs/deploy-render-neon.md), usa ela
# como a única fonte do host/porta a testar, em vez de exigir
# DB_HOST/DB_PORT como uma segunda cópia separada da mesma informação
# (o mesmo raciocínio de fonte única aplicado aqui, não só no settings
# do Django). No VPS, DATABASE_URL nunca é definida — cai exatamente
# no comportamento de sempre, lendo DB_HOST/DB_PORT do .env.
until python -c "
import os, socket, sys
from urllib.parse import urlsplit

database_url = os.environ.get('DATABASE_URL', '')
if database_url:
    parsed = urlsplit(database_url)
    host, port = parsed.hostname, parsed.port or 5432
else:
    host, port = os.environ['DB_HOST'], int(os.environ['DB_PORT'])

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect((host, port))
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
