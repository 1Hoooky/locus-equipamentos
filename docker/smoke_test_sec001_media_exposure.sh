#!/usr/bin/env bash
# Smoke test de segurança — SEC-001 (Auditoria Geral Adversarial, 14/10/2026)
#
# Prova, contra o `docker/nginx.conf` REAL deste repositório (incluído
# verbatim via `include`, nunca copiado/editado por este script), que:
#
#   1. uma requisição anônima para /media/attachments/... é bloqueada
#      (404) — ou seja, o Nginx nunca serve documentos comerciais
#      (PDFs de Proposta/Contrato) direto do disco, contornando
#      `AttachmentDownloadView`;
#   2. o `alias` genérico de /media/ continua funcionando normalmente
#      para qualquer caminho FORA de attachments/ (não quebra um
#      eventual FileField público legítimo no futuro);
#   3. /static/ continua servido normalmente (não é afetado).
#
# Não sobe nenhum container/daemon Docker: usa o binário `nginx` com um
# prefixo e uma porta próprios (isolados de qualquer nginx do sistema),
# e referencia o arquivo real do repositório via `include` — ou seja,
# este script NUNCA copia ou edita `docker/nginx.conf`; se alguém mudar
# esse arquivo, o próximo `./docker/smoke_test_sec001_media_exposure.sh`
# testa a versão nova automaticamente.
#
# Requer: nginx instalado (ex. `apt-get install -y nginx-light`) e curl.
# Não requer Docker. Requer permissão para abrir a porta 80 (o arquivo
# real tem `listen 80` fixo, propositalmente não editado por este
# script) — normalmente root, a mesma exigência do Nginx de produção.
#
# Uso:
#   ./docker/smoke_test_sec001_media_exposure.sh
#
# Saída: 0 e "TODOS OS CHECKS PASSARAM" se tudo estiver correto;
# diferente de 0 e uma mensagem clara identificando qual checagem falhou.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NGINX_CONF="$REPO_ROOT/docker/nginx.conf"
TMP_PREFIX="$(mktemp -d /tmp/sec001_smoke_test.XXXXXX)"
NGINX_PID="$TMP_PREFIX/nginx.pid"

# docker/nginx.conf usa caminhos ABSOLUTOS fixos (/app/media,
# /app/staticfiles — iguais aos do container real) e este script não
# edita/copia o arquivo para parametrizá-los. Por isso o teste precisa
# escrever fixtures nesses caminhos absolutos de verdade. Para não
# arriscar sobrescrever um /app de um host real, este script só
# prossegue se /app ainda NÃO existir — ele cria o diretório, popula as
# fixtures, e remove TUDO (inclusive o /app) ao final. Rode isto num
# container/VM descartável (CI, sandbox de teste), nunca num host onde
# /app já é usado para outra coisa.
if [ -e /app ]; then
    echo "ERRO: /app já existe neste host — este smoke test precisa criar e depois remover" >&2
    echo "      /app/media e /app/staticfiles para testar os caminhos absolutos reais do" >&2
    echo "      nginx.conf. Rode isto num container/VM descartável, não aqui." >&2
    exit 2
fi
CREATED_APP_DIR=1
MEDIA_ROOT="/app/media"
STATIC_ROOT="/app/staticfiles"

cleanup() {
    if [ -f "$NGINX_PID" ]; then
        nginx -p "$TMP_PREFIX" -c "$TMP_PREFIX/wrapper.conf" -s stop 2>/dev/null || true
    fi
    if [ "${CREATED_APP_DIR:-0}" = "1" ]; then
        rm -rf /app
    fi
    rm -rf "$TMP_PREFIX"
}
trap cleanup EXIT

if [ ! -f "$NGINX_CONF" ]; then
    echo "ERRO: não encontrei $NGINX_CONF" >&2
    exit 2
fi
command -v nginx >/dev/null 2>&1 || { echo "ERRO: binário 'nginx' não encontrado (apt-get install -y nginx-light)" >&2; exit 2; }
command -v curl  >/dev/null 2>&1 || { echo "ERRO: binário 'curl' não encontrado" >&2; exit 2; }

mkdir -p "$MEDIA_ROOT/attachments/crm/opportunity/1" "$STATIC_ROOT"
printf '%%PDF-1.4 fixture sintetica - smoke test SEC-001' > "$MEDIA_ROOT/attachments/crm/opportunity/1/PROPOSTA-000001.pdf"
echo "fixture estatica" > "$STATIC_ROOT/smoke_test.txt"
mkdir -p "$MEDIA_ROOT/outro_dominio_futuro"
echo "fixture publica hipotetica fora de attachments/" > "$MEDIA_ROOT/outro_dominio_futuro/arquivo.txt"

# Wrapper mínimo (events{}/http{}) que INCLUI o nginx.conf real do repo
# sem copiá-lo nem editá-lo.
cat > "$TMP_PREFIX/wrapper.conf" << EOF
pid "$NGINX_PID";
events {}
http {
    default_type application/octet-stream;
    access_log "$TMP_PREFIX/access.log";
    error_log  "$TMP_PREFIX/error.log";
    include "$NGINX_CONF";
}
EOF

# 'web' é referenciado em proxy_pass (upstream literal, resolvido já na
# checagem de sintaxe, não só ao iniciar) — por isso isto PRECISA vir
# ANTES do `nginx -t` abaixo, nunca depois: sem isso, até o teste de
# sintaxe falha com "host not found in upstream" num host/container que
# nunca rodou este script antes. Resolver para localhost evita a falha
# sem jamais editar o arquivo do repo.
if ! getent hosts web >/dev/null 2>&1; then
    echo "127.0.0.1 web" >> /etc/hosts 2>/dev/null || echo "AVISO: não consegui adicionar 'web' a /etc/hosts (pode exigir root); se o nginx falhar ao iniciar/checar sintaxe, adicione manualmente." >&2
fi

# O arquivo real tem "listen 80" fixo (não editamos/copiamos o arquivo
# para mudar isso). Por isso este script precisa rodar com permissão
# para abrir a porta 80 (normalmente root) — é a mesma exigência que o
# Nginx real de produção já tem. -p/-c isolam prefixo, PID e logs deste
# teste de qualquer nginx de sistema, então não há conflito de config,
# só a porta 80 em si precisa estar livre no host/container do teste.
if ! nginx -p "$TMP_PREFIX" -c "$TMP_PREFIX/wrapper.conf" -t 2>"$TMP_PREFIX/syntax_check.log"; then
    echo "ERRO: docker/nginx.conf não passou o teste de sintaxe real do nginx:" >&2
    cat "$TMP_PREFIX/syntax_check.log" >&2
    exit 2
fi
echo "[1/5] Sintaxe do docker/nginx.conf real: OK"

nginx -p "$TMP_PREFIX" -c "$TMP_PREFIX/wrapper.conf"
sleep 1
echo "[2/5] nginx real iniciado em prefixo isolado ($TMP_PREFIX), porta 80"

HOST_HEADER="estoque.locuslocacoes.com.br"
FAIL=0

check() {
    local desc="$1" expected="$2" path="$3"
    local got
    got="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $HOST_HEADER" "http://127.0.0.1:80$path" || echo "ERR")"
    if [ "$got" = "$expected" ]; then
        echo "  OK   $desc (esperado $expected, obtido $got)"
    else
        echo "  FALHOU $desc (esperado $expected, obtido $got)" >&2
        FAIL=1
    fi
}

echo "[3/5] Checagem 1 — anônimo não consegue baixar PDF comercial via alias direto:"
check "GET /media/attachments/crm/opportunity/1/PROPOSTA-000001.pdf (anônimo)" "404" \
    "/media/attachments/crm/opportunity/1/PROPOSTA-000001.pdf"

echo "[4/5] Checagem 2 — alias genérico de /media/ continua servindo conteúdo fora de attachments/:"
check "GET /media/outro_dominio_futuro/arquivo.txt" "200" "/media/outro_dominio_futuro/arquivo.txt"

echo "[5/5] Checagem 3 — /static/ não é afetado pela correção:"
check "GET /static/smoke_test.txt" "200" "/static/smoke_test.txt"

echo
if [ "$FAIL" = "0" ]; then
    echo "TODOS OS CHECKS PASSARAM — docker/nginx.conf real bloqueia /media/attachments/ e preserva o resto."
    exit 0
else
    echo "FALHA: pelo menos uma checagem não teve o resultado esperado — ver acima." >&2
    exit 1
fi
