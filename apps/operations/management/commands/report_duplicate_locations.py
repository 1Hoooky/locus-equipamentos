"""
Relatório de Locations duplicadas — 3º reteste manual (item 4): os testes
manuais de double-submit deixaram unidades repetidas no banco (várias
"teste2" etc.). A ORIGEM do problema já foi corrigida (SubmissionGuard com
idempotência no banco); este comando NÃO apaga nada — só lista as
duplicatas e quais delas têm Movement referenciando, para a limpeza
segura ser decidida à parte, com o usuário.

Uso:
    python manage.py report_duplicate_locations

"Duplicata" aqui = mesmo (name, type, client) com mais de uma linha ativa.
Unidades homônimas de clientes DIFERENTES são legítimas por decisão de
projeto (sem UNIQUE(name)) e não aparecem no relatório.

A lógica de agrupamento/contagem mora em
`apps.operations.services.find_duplicate_location_groups()` — reaproveitada
tal como está também pela tela somente-leitura
`apps.operations.views.DuplicateLocationsReportView` (criada para quando não
há acesso a Shell, ex.: Render Free), para nunca haver duas cópias
divergentes da mesma regra. Este comando só formata a mesma informação para
stdout.
"""

from django.core.management.base import BaseCommand

from apps.operations.services import find_duplicate_location_groups


class Command(BaseCommand):
    help = "Lista Locations duplicadas (mesmo name+type+client, ativas) e quais têm Movement referenciando. Não apaga nada."

    def handle(self, *args, **options):
        groups = find_duplicate_location_groups()

        if not groups:
            self.stdout.write(self.style.SUCCESS("Nenhuma Location duplicada encontrada."))
            return

        self.stdout.write(self.style.WARNING(f"{len(groups)} grupo(s) de duplicatas encontrados:\n"))
        for group in groups:
            self.stdout.write(f"Grupo: {group.name!r} · tipo={group.type} · cliente={group.owner_label}")
            for entry in group.entries:
                location = entry.location
                refs = f"movimentos: {entry.movements_as_destination} como destino, {entry.movements_as_origin} como origem"
                marker = "COM REFERÊNCIAS" if entry.has_references else "sem referências"
                self.stdout.write(f"  - Location #{location.pk} (criada em {location.created_at:%d/%m/%Y %H:%M}) — {refs} → {marker}")
            self.stdout.write("")

        self.stdout.write(
            "Nada foi apagado. Locations 'sem referências' são candidatas à limpeza; as 'COM REFERÊNCIAS' "
            "precisam de decisão caso a caso (o histórico de movimentações aponta para elas)."
        )
