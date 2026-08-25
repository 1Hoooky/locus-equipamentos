"""
Filtro combinado de equipamentos (especificação, seção 15/12: "Filtros
combinados serão importantes" / tela de listagem). Compartilhado entre a
listagem (`EquipmentListView`) e a exportação (`EquipmentExportView`) —
a exportação precisa respeitar exatamente os mesmos filtros da tela, não
uma lógica reimplementada à parte que pode divergir com o tempo.
"""

import uuid

from django.db.models import Q, QuerySet
from django.http import QueryDict


def filter_equipment_queryset(queryset: QuerySet, params: QueryDict) -> QuerySet:
    q = params.get("q", "").strip()
    if q:
        queryset = queryset.filter(Q(patrimonio__icontains=q) | Q(serial_number__icontains=q))

    # "category" e "model" filtram por chave primária (FK). Um valor não
    # numérico (ex.: "?category=abc", vindo de uma URL adulterada à mão)
    # faz o ORM levantar ValueError ao tentar preparar o lookup — 500 em
    # vez de simplesmente ignorar um filtro inválido. "status"/"condition"
    # não têm esse problema (são CharField de escolhas: valor inválido só
    # resulta em zero linhas). Corrigido na auditoria final da Fase 1
    # (2026-08-25): ignora silenciosamente category/model não numéricos,
    # em vez de propagar o erro.
    for field in ("status", "condition", "category", "model"):
        value = params.get(field)
        if not value:
            continue
        if field in ("category", "model") and not value.isdigit():
            continue
        queryset = queryset.filter(**{field: value})

    # "batch" (UUID) — usado pela tela de resultado do cadastro em lote
    # ("Ver equipamentos criados", equipment/batch_result.html) para
    # filtrar só os equipamentos daquela operação. Mesmo cuidado de
    # category/model acima: um valor que não seja um UUID válido é
    # ignorado, não derruba a listagem.
    batch_value = params.get("batch")
    if batch_value:
        try:
            uuid.UUID(batch_value)
        except (ValueError, AttributeError, TypeError):
            pass
        else:
            queryset = queryset.filter(batch_id=batch_value)

    return queryset
