"""
Agregação de `Equipment` por `EquipmentModel` para a listagem agrupada em
`/equipamentos/` (melhoria de UX/consulta — NÃO é uma mudança de domínio:
só leitura, nenhuma escrita, nenhum model/migration novo).

Por que este módulo existe separado de `apps/equipment/services.py`: lá
vivem as operações de ESCRITA de domínio (criar/alterar equipamento,
status, condição, reclassificação...). Isto aqui é 100% consulta —
mantê-lo à parte deixa claro que nada aqui decide regra de negócio, só
formata contagens para a tela.

Ponto central de performance (auditoria pedida antes desta etapa): os
contadores por modelo são calculados com UM ÚNICO `GROUP BY` via
`.values().annotate(Count(..., filter=Q(...)))` — nunca um loop chamando
`.filter().count()` por modelo (isso seria N+1, e pioraria conforme a
frota cresce). `build_model_groups` sempre executa exatamente 1 query,
independente de o resultado ter 3 ou 300 modelos distintos — ver
`apps/equipment/tests/test_equipment_grouped_listing.py`, que prova isso
comparando o número de queries com 10 modelos e com 100 modelos.
"""

from dataclasses import dataclass, field

from django.db.models import Count, Q, QuerySet

from apps.equipment.models import Status

# (chave interna, valor real do Status, classe de badge JÁ existente no
# design system, rótulo singular, rótulo plural) — os 4 valores são
# exatamente `Status.choices` (apps/equipment/models.py); nenhum status
# novo foi inventado, e a classe CSS de cada um é a MESMA já usada na
# tabela anterior (templates/equipment/list.html, antes desta etapa):
# DISPONIVEL->badge-success, EM_OPERACAO->badge-info,
# MANUTENCAO->badge-warning, INATIVO->badge-neutral (o "else" da tabela
# antiga). Rótulos singular/plural escritos à mão porque o filtro
# `|pluralize` do Django só sabe acrescentar sufixo regular ("-s"), o que
# quebraria palavras irregulares em português como "disponível"/
# "disponíveis".
_STATUS_BADGES = (
    ("disponiveis", Status.DISPONIVEL, "badge-success", "disponível", "disponíveis"),
    ("em_operacao", Status.EM_OPERACAO, "badge-info", "em operação", "em operação"),
    ("manutencao", Status.MANUTENCAO, "badge-warning", "manutenção", "manutenção"),
    ("inativos", Status.INATIVO, "badge-neutral", "inativo", "inativos"),
)


@dataclass
class ModelGroup:
    """Uma linha/card de modelo na listagem agrupada, já com os badges prontos para o template."""

    model_id: int
    model_name: str
    model_code: str
    category_name: str
    total: int
    # [(rótulo, contagem, classe_css), ...] — só os status com contagem > 0
    # (decisão aprovada: "badge com valor zero pode ser omitido").
    status_badges: list = field(default_factory=list)


def build_model_groups(queryset: QuerySet) -> list[ModelGroup]:
    """
    `queryset` já deve chegar filtrada (mesma `filter_equipment_queryset`
    usada pela listagem e pela exportação — nenhuma lógica de filtro
    duplicada aqui) e restrita a equipamento ativo. Modelos sem nenhum
    equipamento no resultado filtrado simplesmente não aparecem no
    retorno — é o próprio `GROUP BY` que garante isso (não é um filtro
    extra escrito à parte): sem linha correspondente na consulta, sem
    grupo.
    """

    rows = (
        queryset.values("model_id", "model__name", "model__code", "model__category__name")
        .annotate(
            total=Count("id"),
            **{key: Count("id", filter=Q(status=status_value)) for key, status_value, _, _, _ in _STATUS_BADGES},
        )
        .order_by("model__category__name", "model__name")
    )

    groups = []
    for row in rows:
        badges = []
        for key, _status_value, css_class, singular, plural in _STATUS_BADGES:
            count = row[key]
            if count:
                badges.append((singular if count == 1 else plural, count, css_class))
        groups.append(
            ModelGroup(
                model_id=row["model_id"],
                model_name=row["model__name"],
                model_code=row["model__code"],
                category_name=row["model__category__name"],
                total=row["total"],
                status_badges=badges,
            )
        )
    return groups
