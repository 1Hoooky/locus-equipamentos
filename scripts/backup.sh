#!/usr/bin/env bash
#
# P0-06 / INFRA-002 — backup completo do LocusHub: PostgreSQL + MEDIA_ROOT
# (todo o conteúdo, não só PDFs conhecidos hoje) + manifest/checksums.
#
# Um backup incompleto NUNCA deve parecer um backup válido: tudo é
# construído num diretório temporário, validado passo a passo (incluindo
# validação estrutural E de segurança do archive de media — ver
# scripts/validate_media_archive.py — e a consistência da própria ORIGEM
# via manage.py verify_media_integrity, descoberta num smoke real: uma
# origem já inconsistente ANTES do backup nunca deve virar um backup
# "válido"), e só promovido (rename atômico) para dentro de BACKUP_DIR
# depois que TODAS as validações passarem. Se qualquer etapa falhar, o
# script sai com código != 0, o diretório temporário é removido (nunca
# promovido), a retenção não roda, e nenhum backup anterior válido é
# afetado.
#
# O diretório final de cada backup tem nome intrinsecamente único
# (timestamp + sufixo aleatório reaproveitado do próprio `mktemp`), para
# que duas execuções concorrentes no mesmo segundo nunca apontem para o
# mesmo destino — ver seção de "hardening final" no relatório do P0-06.
#
# Uso:
#   scripts/backup.sh
#
# Variáveis de ambiente (todas opcionais, com default):
#   BACKUP_DIR              diretório onde os backups ficam (default: ./backups)
#   COMPOSE_FILE_ARG         ex.: "-f docker-compose.yml" (default: vazio, usa o Compose padrão do diretório atual)
#   DB_SERVICE               nome do serviço do Postgres no Compose (default: db)
#   WEB_SERVICE              nome do serviço com MEDIA_ROOT montado (default: web)
#   BACKUP_RETENTION_DAYS    dias de retenção, inteiro >= 0 (default: 30) — 0 desativa a retenção
#
# Pré-requisitos no HOST que roda este script (nunca dentro dos
# containers da aplicação): `docker`, `tar`, `sha256sum`, `python3`
# (usado só para scripts/validate_media_archive.py — biblioteca padrão,
# sem dependência de Django/venv do projeto). NÃO precisa de
# `pg_dump`/`pg_restore` instalados no host — a validação estrutural do
# dump roda dentro do próprio container `db` já em execução (ver seção
# 4), nunca precisa de uma imagem/container adicional.
#
# Este script NUNCA lê nem imprime DB_PASSWORD/DJANGO_SECRET_KEY/tokens —
# o `pg_dump` roda DENTRO do container `db`, usando as variáveis que já
# existem lá (POSTGRES_USER/POSTGRES_DB, definidas pelo próprio
# docker-compose.yml), nunca uma cópia lida do host.

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
COMPOSE_FILE_ARG="${COMPOSE_FILE_ARG:-}"
DB_SERVICE="${DB_SERVICE:-db}"
WEB_SERVICE="${WEB_SERVICE:-web}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

compose() {
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILE_ARG "$@"
}

log() {
  printf '[backup.sh] %s\n' "$*" >&2
}

fail() {
  log "ERRO: $*"
  exit 1
}

# ---------------------------------------------------------------------------
# 0. Validar configuração ANTES de fazer qualquer trabalho pesado —
# um BACKUP_RETENTION_DAYS inválido aborta aqui, nunca chega perto da
# retenção (que só roda no fim, depois de promover o backup novo).
# ---------------------------------------------------------------------------
case "$BACKUP_RETENTION_DAYS" in
  ''|*[!0-9]*)
    fail "BACKUP_RETENTION_DAYS inválido: '$BACKUP_RETENTION_DAYS' (precisa ser um inteiro >= 0, ex.: 0, 30, 90)."
    ;;
esac

timestamp="$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
tmp_dir="$(mktemp -d "${BACKUP_DIR}/.tmp-XXXXXXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

# Nome final intrinsecamente único: reaproveita o sufixo aleatório que o
# próprio `mktemp` já garantiu ser único (sem depender de um check +
# mv separados, que teria janela de corrida entre duas execuções
# concorrentes no mesmo segundo).
tmp_suffix="$(basename "$tmp_dir")"
tmp_suffix="${tmp_suffix#.tmp-}"
final_dir="${BACKUP_DIR}/${timestamp}-${tmp_suffix}"

log "Backup iniciado em $(date -u --iso-8601=seconds) — diretório temporário: $tmp_dir"

# ---------------------------------------------------------------------------
# 1/2. Dump do PostgreSQL — formato custom (-Fc), permite validação
# estrutural depois com `pg_restore --list` sem tocar em nenhum banco
# real. Executa DENTRO do container `db`: $POSTGRES_USER/$POSTGRES_DB já
# existem nesse ambiente (docker-compose.yml), nunca lidos/impressos
# aqui no host.
# ---------------------------------------------------------------------------
log "Gerando dump do PostgreSQL (serviço '$DB_SERVICE', formato custom)..."
# single quotes são de propósito: $POSTGRES_USER/$POSTGRES_DB devem expandir DENTRO
# do container (onde já existem), nunca no host.
# shellcheck disable=SC2016
if ! compose exec -T "$DB_SERVICE" sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$tmp_dir/database.dump"; then
  fail "pg_dump falhou."
fi
[ -s "$tmp_dir/database.dump" ] || fail "database.dump ficou vazio."

# ---------------------------------------------------------------------------
# 3. Archive de TODO o MEDIA_ROOT (não só PDFs conhecidos hoje — cobre
# contratos, propostas, fotos, categoria OUTRO e qualquer FileField
# futuro sob MEDIA_ROOT). Preserva estrutura relativa de caminhos
# (tar -C /app media -> tudo sob "media/..."). Executa DENTRO do
# container `web`, que tem o volume de media montado em /app/media.
# ---------------------------------------------------------------------------
log "Gerando archive de MEDIA_ROOT (serviço '$WEB_SERVICE')..."
if ! compose exec -T "$WEB_SERVICE" tar -C /app -czf - media > "$tmp_dir/media.tar.gz"; then
  fail "tar de MEDIA_ROOT falhou."
fi
[ -s "$tmp_dir/media.tar.gz" ] || fail "media.tar.gz ficou vazio."

# ---------------------------------------------------------------------------
# 3b. Verificar a consistência da ORIGEM (antes de aceitar este backup).
#
# Um Attachment.file que já não tem arquivo físico correspondente ANTES
# deste backup (ex.: perda parcial de disco, edição manual indevida fora
# do fluxo de create_attachment(), ou qualquer outra causa anterior) não
# pode virar um backup "válido" — promover esse backup faria o problema
# ser só herdado/mascarado (um restore a partir dele reproduziria a mesma
# referência quebrada, sem nenhum sinal de que ela já existia ANTES do
# backup, não depois). Reaproveita o mesmo comando read-only que
# scripts/restore.sh já usa depois de um restore — ver
# apps/attachments/management/commands/verify_media_integrity.py. Não
# apaga nem recria nenhum Attachment/arquivo, não altera o banco nem
# MEDIA_ROOT de origem.
# ---------------------------------------------------------------------------
log "Verificando consistência da ORIGEM (PostgreSQL × MEDIA_ROOT, manage.py verify_media_integrity, serviço '$WEB_SERVICE')..."
if ! compose exec -T "$WEB_SERVICE" python manage.py verify_media_integrity; then
  fail "A ORIGEM já está inconsistente: pelo menos um Attachment.file não tem arquivo físico correspondente ANTES deste backup (ver mensagens acima). Backup recusado — nenhum backup incompleto/inconsistente foi promovido, nenhum backup anterior válido foi afetado, e o banco/MEDIA_ROOT de origem não foram alterados por este script. Corrija a inconsistência na origem antes de tentar um novo backup."
fi

# ---------------------------------------------------------------------------
# 4. Validar os dois artefatos ANTES de aceitar o backup.
#
# Validação do dump: roda DENTRO do container `db` que já está em
# execução (pg_restore --list só lê o TOC do archive — não conecta a
# nenhum banco, não altera o PostgreSQL real). Isso evita a dependência
# extra de um `docker run` com uma segunda imagem (`postgres:16`), que
# exigiria rede/registry se essa imagem não estivesse já em cache — algo
# que o Compose já garante para o próprio container `db`, mas não para
# um `docker run` solto.
# ---------------------------------------------------------------------------
log "Validando estrutura do dump (pg_restore --list, dentro do container '$DB_SERVICE' já em execução)..."
if ! compose exec -T "$DB_SERVICE" pg_restore --list < "$tmp_dir/database.dump" > /dev/null; then
  fail "database.dump não passou pg_restore --list — dump corrompido/incompleto."
fi

log "Validando archive de media (estrutura: tar -tzf)..."
if ! tar -tzf "$tmp_dir/media.tar.gz" > /dev/null; then
  fail "media.tar.gz não passou tar -tzf — archive corrompido/incompleto."
fi

log "Validando archive de media (segurança: scripts/validate_media_archive.py)..."
if ! python3 "$SCRIPT_DIR/validate_media_archive.py" "$tmp_dir/media.tar.gz"; then
  fail "media.tar.gz contém membro inseguro (caminho absoluto, '..', symlink, hardlink, device ou FIFO) — ver mensagens acima. Backup recusado."
fi

# ---------------------------------------------------------------------------
# 5. Checksums + metadata (nunca segredo nenhum).
# ---------------------------------------------------------------------------
log "Gerando SHA256SUMS e metadata.txt..."
(
  cd "$tmp_dir"
  sha256sum database.dump media.tar.gz > SHA256SUMS
  sha256sum -c SHA256SUMS > /dev/null || fail "SHA256SUMS não validou imediatamente após ser gerado."
)

git_sha="desconhecido"
if git rev-parse HEAD > /dev/null 2>&1; then
  git_sha="$(git rev-parse HEAD)"
fi

cat > "$tmp_dir/metadata.txt" <<EOF
backup_format_version=1
timestamp_utc=$(date -u --iso-8601=seconds)
git_sha=$git_sha
artifacts=database.dump,media.tar.gz,SHA256SUMS
EOF

# ---------------------------------------------------------------------------
# 6. Só agora, com TUDO validado, promove atomicamente (rename, mesmo
# filesystem) o diretório temporário para um backup válido e definitivo.
# O nome de $final_dir já é intrinsecamente único (timestamp + sufixo
# aleatório do mktemp), então duas execuções no mesmo segundo nunca
# calculam o mesmo destino — a checagem abaixo é só uma segunda camada
# de defesa (nunca deveria disparar), não a única proteção contra
# colisão.
# ---------------------------------------------------------------------------
if [ -e "$final_dir" ]; then
  fail "Já existe um backup em $final_dir (colisão inesperada de nome único) — abortando sem promover."
fi
mv "$tmp_dir" "$final_dir"
trap - EXIT
log "Backup promovido com sucesso: $final_dir"

# ---------------------------------------------------------------------------
# 7. Retenção — só roda DEPOIS de promover este backup novo com sucesso.
# Nunca apaga nada se este backup falhou antes de chegar aqui (o `set -e`
# já teria encerrado o script). Remove só backups MAIS ANTIGOS que o
# período configurado; nunca o que acabou de ser criado.
# ---------------------------------------------------------------------------
if [ "$BACKUP_RETENTION_DAYS" -gt 0 ]; then
  log "Aplicando retenção de $BACKUP_RETENTION_DAYS dia(s)..."
  find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '[0-9]*-*' \
    -mtime "+$BACKUP_RETENTION_DAYS" -not -path "$final_dir" -print \
    | while IFS= read -r old_dir; do
        log "Removendo backup antigo (> ${BACKUP_RETENTION_DAYS}d): $old_dir"
        rm -rf "$old_dir"
      done
else
  log "Retenção desativada (BACKUP_RETENTION_DAYS=0)."
fi

log "Concluído."
