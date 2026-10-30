"""
P0-06 / INFRA-002 (estratégia de backup) — verificação de consistência
entre PostgreSQL e MEDIA_ROOT: para cada `Attachment.file` não vazio,
confirma que o arquivo físico correspondente existe.

Usa a API oficial de storage do Django (`attachment.file.storage.exists`)
em vez de concatenar `MEDIA_ROOT` manualmente ou assumir um filesystem
local via `.path()` — funciona hoje com o backend de filesystem (único em
uso no projeto) e continua funcionando sem alteração se um backend
diferente (ex.: S3-compatible) for adotado no futuro, sem precisar de
nenhum caso especial aqui (não é implementado nesta rodada — ver Opção C
rejeitada na especificação do P0-06).

Não calcula checksum de cada `Attachment` individualmente (fora do
objetivo desta rodada — ver relatório de implementação do P0-06, seção
"estratégia final de consistência"). O objetivo é só detectar o sintoma
exato do INFRA-002: o banco referenciar um arquivo que não existe mais
fisicamente (ex.: depois de um restore incompleto, perda parcial de
disco, ou qualquer outra causa).

Não apaga nada, não altera nenhum registro — só lê e reporta.

Uso:
    python manage.py verify_media_integrity

Saída: código 0 se todos os arquivos referenciados existem; código 1 se
pelo menos um `Attachment.file` estiver ausente (usado por
`scripts/restore.sh` para decidir se um restore terminou íntegro ou deve
ser tratado como falha).
"""

from django.core.management.base import BaseCommand

from apps.attachments.models import Attachment


class Command(BaseCommand):
    help = (
        "Confirma que todo Attachment.file não vazio existe no storage configurado. "
        "Não apaga nada. Sai com código 1 se encontrar qualquer referência quebrada."
    )

    def handle(self, *args, **options):
        # Exclui linhas sem arquivo (campo nunca foi preenchido) — nunca
        # um caminho legítimo de "arquivo ausente", é só um Attachment
        # sem file (hoje não deveria existir, já que create_attachment()
        # sempre grava um file, mas o campo é `blank=False`/sem default
        # de banco que force isso — checagem defensiva, não assume).
        attachments = Attachment.objects.exclude(file="").exclude(file__isnull=True).order_by("pk")

        total = 0
        missing = []
        for attachment in attachments.iterator():
            total += 1
            if not attachment.file.storage.exists(attachment.file.name):
                missing.append((attachment.pk, attachment.file.name))

        if not missing:
            self.stdout.write(self.style.SUCCESS(f"OK — {total} Attachment(s) com arquivo verificado(s), nenhuma referência quebrada."))
            return

        self.stdout.write(self.style.ERROR(f"FALHA — {len(missing)} de {total} Attachment(s) referenciam arquivo ausente:"))
        for pk, name in missing:
            self.stdout.write(f"  - Attachment #{pk}: file={name!r} não existe no storage configurado")

        raise SystemExit(1)
