#!/usr/bin/env bash
#
# P0-06 / INFRA-002 — restore de um backup gerado por scripts/backup.sh.
#
# Tratado como operação potencialmente DESTRUTIVA. Por padrão este
# script só VALIDA o backup (checksums + estrutura do dump + estrutura
# E segurança do archive de media — ver scripts/validate_media_archive.py)
# e PARA — nenhum banco/MEDIA_ROOT real é tocado.
#
# A restauração de fato só acontece com confirmação explícita
# (CONFIRM=yes), e o destino (banco + MEDIA_ROOT) precisa estar
# GENUINAMENTE VAZIO antes de começar. Não existe mais um caminho para
# sobrescrever um destino não vazio (ver "hardening final" do P0-06): se
# o banco já tem alguma tabela, ou MEDIA_ROOT já tem algum arquivo
# (incluindo ocultos), o restore recusa e aborta, sem exceção. O
# procedimento oficial de disaster recovery é: preparar um destino limpo
# (banco novo vazio + MEDIA_ROOT vazio) -> restaurar -> verificar ->
# só então colocar em serviço.
#
# Uso:
#   scripts/restore.sh <diretório-do-backup>                 # valida só, não restaura
#   CONFIRM=yes scripts/restore.sh <diretório-do-backup>      # restaura, só se o destino estiver vazio
#
# Variáveis de ambiente:
#   CONFIRM     "yes" para de fato restaurar (default: valida só, não restaura)
#   COMPOSE_FILE_ARG, DB_SERVICE, WEB_SERVICE   mesmos defaults de scripts/backup.sh
#
# Este script NUNCA lê/imprime segredos — o `pg_restore` roda dentro do
# container `db`, usando as variáveis já definidas lá.
#
# Importante: se a verificação final (verify_media_integrity) falhar
# DEPOIS do pg_restore e da extração do media já terem rodado, o destino
# já foi alterado — este script NÃO faz rollback automático. Um restore
# que termina com falha deixa o destino num estado inválido/descartável:
# ele deve ser recriado vazio (banco novo + MEDIA_ROOT vazio) antes de
# tentar novamente. Como o restore só aceita destino vazio para começar,
# o "pior caso" de uma falha é sempre um destino descartável que nunca
# estava em produção — nunca um ambiente real que já estava servindo
# tráfego.

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "${1:-}" = "" ]; then
  echo "Uso: $0 <diretório-do-backup>" >&2
  exit 2
fi
BACKUP_PATH="$1"

COMPOSE_FILE_ARG="${COMPOSE_FILE_ARG:-}"
DB_SERVICE="${DB_SERVICE:-db}"
WEB_SERVICE="${WEB_SERVICE:-web}"
CONFIRM="${CONFIRM:-no}"

compose() {
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILE_ARG "$@"
}

log() { printf '[restore.sh] %s\n' "$*" >&2; }
fail() { log "ERRO: $*"; exit 1; }

[ -d "$BACKUP_PATH" ] || fail "Diretório de backup não encontrado: $BACKUP_PATH"
for artifact in database.dump media.tar.gz SHA256SUMS metadata.txt; do
  [ -f "$BACKUP_PATH/$artifact" ] || fail "Artefato ausente em $BACKUP_PATH: $artifact"
done

log "Backup encontrado: $BACKUP_PATH"
sed 's/^/[restore.sh]   /' "$BACKUP_PATH/metadata.txt" >&2

# ---------------------------------------------------------------------------
# Validação — SEMPRE roda, antes de tocar em qualquer destino.
# ---------------------------------------------------------------------------
log "Validando checksums (SHA256SUMS)..."
(cd "$BACKUP_PATH" && sha256sum -c SHA256SUMS) || fail "SHA256SUMS não validou — backup corrompido/incompleto. Restore recusado."

log "Validando estrutura do dump (pg_restore --list, dentro do container '$DB_SERVICE' já em execução)..."
compose exec -T "$DB_SERVICE" pg_restore --list < "$BACKUP_PATH/database.dump" > /dev/null \
  || fail "database.dump não passou pg_restore --list. Restore recusado."

log "Validando archive de media (estrutura: tar -tzf)..."
tar -tzf "$BACKUP_PATH/media.tar.gz" > /dev/null \
  || fail "media.tar.gz não passou tar -tzf. Restore recusado."

log "Validando archive de media (segurança: scripts/validate_media_archive.py)..."
python3 "$SCRIPT_DIR/validate_media_archive.py" "$BACKUP_PATH/media.tar.gz" \
  || fail "media.tar.gz contém membro inseguro (caminho absoluto, '..', symlink, hardlink, device ou FIFO) — ver mensagens acima. Restore recusado antes de tocar o destino."

log "Backup validado com sucesso."

if [ "$CONFIRM" != "yes" ]; then
  log "CONFIRM != yes — validação concluída, NENHUM dado foi tocado."
  log "Para restaurar de fato (exige destino vazio): CONFIRM=yes $0 $BACKUP_PATH"
  exit 0
fi

# ---------------------------------------------------------------------------
# Confirmação explícita dada — o destino precisa estar genuinamente
# vazio. Não existe mais override (FORCE) para sobrescrever um destino
# não vazio: se qualquer um dos dois (banco ou MEDIA_ROOT) já tiver
# dados, o restore recusa e para aqui, sem tocar em nada.
# ---------------------------------------------------------------------------
log "CONFIRM=yes — verificando se o destino está genuinamente vazio antes de restaurar..."

# single quotes são de propósito: $POSTGRES_USER/$POSTGRES_DB devem expandir DENTRO
# do container (onde já existem), nunca no host.
# shellcheck disable=SC2016
db_table_count="$(compose exec -T "$DB_SERVICE" sh -c \
  'psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from pg_tables where schemaname='"'"'public'"'"';"')"
db_table_count="$(echo "$db_table_count" | tr -d '[:space:]')"

media_has_files="$(compose exec -T "$WEB_SERVICE" sh -c 'find /app/media -mindepth 1 -print -quit 2>/dev/null || true')"

if [ "${db_table_count:-0}" != "0" ]; then
  fail "O banco de destino já tem $db_table_count tabela(s) em 'public' — destino não está vazio. Restore recusado (não existe override: prepare um banco novo vazio e tente novamente)."
fi
if [ -n "${media_has_files:-}" ]; then
  fail "MEDIA_ROOT de destino não está vazio — encontrado pelo menos: $media_has_files. Restore recusado (não existe override: prepare um MEDIA_ROOT vazio e tente novamente)."
fi

log "Destino confirmado vazio (0 tabelas em 'public', MEDIA_ROOT sem nenhum arquivo)."

# ---------------------------------------------------------------------------
# Restauração de fato. Se qualquer passo a partir daqui falhar, o
# destino já pode ter sido parcialmente alterado — não há rollback
# automático (ver cabeçalho). O restore é então reportado como falho e
# o destino deve ser descartado/recriado vazio antes de tentar de novo.
# ---------------------------------------------------------------------------
log "Restaurando PostgreSQL (serviço '$DB_SERVICE')..."
# single quotes são de propósito: $POSTGRES_USER/$POSTGRES_DB devem expandir DENTRO
# do container (onde já existem), nunca no host.
# shellcheck disable=SC2016
compose exec -T "$DB_SERVICE" sh -c 'pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$BACKUP_PATH/database.dump" \
  || fail "pg_restore falhou. Destino pode estar parcialmente alterado — descarte-o e recrie vazio antes de tentar de novo."

log "Restaurando MEDIA_ROOT (serviço '$WEB_SERVICE')..."
compose exec -T "$WEB_SERVICE" sh -c 'tar -C /app -xzf -' \
  < "$BACKUP_PATH/media.tar.gz" \
  || fail "Extração do archive de media falhou. Destino pode estar parcialmente alterado — descarte-o e recrie vazio antes de tentar de novo."

log "Verificando consistência PostgreSQL × MEDIA_ROOT (manage.py verify_media_integrity)..."
if ! compose exec -T "$WEB_SERVICE" python manage.py verify_media_integrity; then
  fail "Verificação de integridade falhou — pelo menos um Attachment.file está sem arquivo físico correspondente. RESTORE = FALHA. O destino já foi alterado (pg_restore + extração do media já rodaram) e deve ser tratado como inválido/descartável — recrie-o vazio antes de tentar de novo. Nenhum rollback automático foi ou será feito."
fi

log "Restore concluído e verificado com sucesso."
