"""
Filtro combinado de equipamentos (especificação, seção 15/12: "Filtros
combinados serão importantes" / tela de listagem). Compartilhado entre a
listagem (`EquipmentListView`) e a exportação (`EquipmentExportView`) —
a exportação precisa respeitar exatamente os mesmos filtros da tela, não
uma lógica reimplementada à parte que pode divergir com o tempo.
"""

from django.db.models import Q, QuerySet
from django.http import QueryDict


def filter_equipment_queryset(queryset: QuerySet, params: QueryDict) -> QuerySet:
    q = params.get("q", "").strip()
    if q:
        queryset = queryset.filter(Q(patrimonio__icontains=q) | Q(serial_number__icontains=q))

    for field in ("status", "condition", "category", "model"):
        value = params.get(field)
        if value:
            queryset = queryset.filter(**{field: value})

    return queryset
