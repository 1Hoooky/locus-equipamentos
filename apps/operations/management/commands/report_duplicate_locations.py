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
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.operations.models import Location, Movement


class Command(BaseCommand):
    help = "Lista Locations duplicadas (mesmo name+type+client, ativas) e quais têm Movement referenciando. Não apaga nada."

    def handle(self, *args, **options):
        duplicate_groups = (
            Location.objects.filter(is_active=True)
            .values("name", "type", "client")
            .annotate(quantidade=Count("id"))
            .filter(quantidade__gt=1)
            .order_by("name")
        )

        if not duplicate_groups:
            self.stdout.write(self.style.SUCCESS("Nenhuma Location duplicada encontrada."))
            return

        self.stdout.write(self.style.WARNING(f"{len(duplicate_groups)} grupo(s) de duplicatas encontrados:\n"))
        for group in duplicate_groups:
            locations = Location.objects.filter(
                is_active=True, name=group["name"], type=group["type"], client_id=group["client"]
            ).select_related("client").order_by("pk")
            first = locations.first()
            owner = first.client.display_name() if first.client_id else "(interna, sem cliente)"
            self.stdout.write(f"Grupo: {group['name']!r} · tipo={group['type']} · cliente={owner}")
            for location in locations:
                as_destination = Movement.objects.filter(destination_location=location).count()
                as_origin = Movement.objects.filter(origin_location=location).count()
                equipment_here = location.equipment_set.count() if hasattr(location, "equipment_set") else None
                refs = f"movimentos: {as_destination} como destino, {as_origin} como origem"
                marker = "COM REFERÊNCIAS" if (as_destination or as_origin) else "sem referências"
                self.stdout.write(f"  - Location #{location.pk} (criada em {location.created_at:%d/%m/%Y %H:%M}) — {refs} → {marker}")
            self.stdout.write("")

        self.stdout.write(
            "Nada foi apagado. Locations 'sem referências' são candidatas à limpeza; as 'COM REFERÊNCIAS' "
            "precisam de decisão caso a caso (o histórico de movimentações aponta para elas)."
        )
