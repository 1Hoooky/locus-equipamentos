"""
Filtros de listagem de `Maintenance`/`Cleaning` — mesmo padrão de
`apps.equipment.filters.filter_equipment_queryset()`: função pura que
recebe a queryset base e o `QueryDict` da requisição, devolve a queryset
filtrada. Nenhuma regra de domínio aqui — só busca/filtro de UI.
"""

from django.db.models import Q, QuerySet


def filter_maintenance_queryset(queryset: QuerySet, params) -> QuerySet:
    q = params.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(equipment__patrimonio__icontains=q) | Q(equipment__model__name__icontains=q)
        )

    for field in ("status", "maintenance_type"):
        value = params.get(field)
        if value:
            queryset = queryset.filter(**{field: value})

    return queryset


def filter_cleaning_queryset(queryset: QuerySet, params) -> QuerySet:
    q = params.get("q", "").strip()
    if q:
        queryset = queryset.filter(
            Q(equipment__patrimonio__icontains=q) | Q(equipment__model__name__icontains=q)
        )
    return queryset
