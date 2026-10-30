#!/usr/bin/env python3
"""
P0-06 / INFRA-002 — validação estrutural e de segurança de um
``media.tar.gz`` gerado por ``scripts/backup.sh``, usada tanto por
``scripts/backup.sh`` (antes de promover o backup) quanto por
``scripts/restore.sh`` (antes de extrair, antes de tocar em qualquer
destino).

Não basta confirmar que o arquivo é um gzip/tar bem formado (``tar -tzf``
já faz isso, mas não impede um archive malicioso com checksum
recalculado por quem o gerou). Este script abre o archive com o módulo
padrão ``tarfile`` do Python e inspeciona cada membro individualmente,
rejeitando qualquer coisa que não seja estritamente um diretório ou
arquivo regular dentro da árvore ``media/`` esperada:

- caminho absoluto (``/etc/...``);
- qualquer componente ``..`` no nome (path traversal, ex.:
  ``../../escape``, ``../escape``);
- qualquer membro fora de ``media/`` (ou que não seja exatamente
  ``media``);
- symlink (apontando para dentro ou para fora — nenhum symlink é
  legítimo dentro de ``MEDIA_ROOT`` hoje);
- hardlink;
- device (character/block);
- FIFO;
- qualquer outro tipo que não seja arquivo regular ou diretório.

Não extrai nada — só lê os cabeçalhos (``getmembers()``) e reporta. Sai
com código 0 se o archive for seguro, ou código 1 (listando TODOS os
membros inseguros encontrados, não só o primeiro) se encontrar qualquer
violação.

Uso:
    python3 scripts/validate_media_archive.py <caminho-para-media.tar.gz>
"""

import os
import sys
import tarfile

ALLOWED_TOP = "media"


def _is_outside_media(name: str) -> bool:
    normalized = os.path.normpath(name)
    return normalized != ALLOWED_TOP and not normalized.startswith(ALLOWED_TOP + "/")


def validate(path):
    """Retorna a lista de violações encontradas (vazia = archive seguro)."""
    violations = []

    try:
        archive = tarfile.open(path, mode="r:*")
    except (tarfile.TarError, OSError) as exc:
        return [f"não foi possível abrir o archive como tar/gzip válido: {exc}"]

    try:
        for member in archive.getmembers():
            name = member.name

            if name in ("", "."):
                continue

            if name.startswith("/"):
                violations.append(f"{name!r}: caminho absoluto não permitido dentro do archive")
                continue

            if ".." in name.split("/"):
                violations.append(f"{name!r}: componente '..' não permitido (path traversal)")
                continue

            if _is_outside_media(name):
                violations.append(f"{name!r}: fora da árvore '{ALLOWED_TOP}/' esperada")
                continue

            if member.issym():
                violations.append(f"{name!r}: symlink não permitido dentro de MEDIA_ROOT (-> {member.linkname!r})")
                continue

            if member.islnk():
                violations.append(f"{name!r}: hardlink não permitido dentro de MEDIA_ROOT (-> {member.linkname!r})")
                continue

            if member.ischr() or member.isblk():
                violations.append(f"{name!r}: device (character/block) não permitido dentro de MEDIA_ROOT")
                continue

            if member.isfifo():
                violations.append(f"{name!r}: FIFO não permitido dentro de MEDIA_ROOT")
                continue

            if not (member.isreg() or member.isdir()):
                violations.append(f"{name!r}: tipo de entrada não permitido (tarfile type={member.type!r})")
                continue
    finally:
        archive.close()

    return violations


def main(argv):
    if len(argv) != 2:
        print("Uso: validate_media_archive.py <caminho-para-media.tar.gz>", file=sys.stderr)
        return 2

    path = argv[1]
    violations = validate(path)

    if violations:
        print(f"REJEITADO — {len(violations)} membro(s) inseguro(s) em {path}:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print(f"OK — archive de media validado, nenhum membro inseguro: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
