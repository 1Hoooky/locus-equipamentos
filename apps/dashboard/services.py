"""
Consultas da Home operacional — etapa de UX/UI, 28/08/2026 (ver
AUDITORIA_UX_HOME_NAVEGACAO_QR.md, itens [26]-[29]).

Escopo desta PRIMEIRA versão (decisão aprovada, item 17 do briefing):

  CARDS: Disponíveis, Em operação, Em manutenção, Manutenções abertas.
  CONTEÚDO: Movimentações recentes, Manutenções abertas (lista),
  Equipamentos que exigem atenção.

Ficam FORA de propósito (decisão aprovada): higienizações recentes, total
de clientes, total de unidades, qualquer gráfico, métricas por
funcionário, médias de tempo, ou qualquer indicador não listado acima.
Nenhum indicador foi inventado — todos usam campos/modelos que já
existem e já são escritos pelos fluxos operacionais atuais.

Orçamento de consultas (auditoria, item [28]): cada função abaixo é UMA
única consulta — agregação (`Count`) ou slice limitado com
`select_related`, nunca um `.count()` dentro de laço. `build_home_context`
soma no máximo 6 consultas ao todo, independente de quantos registros
existam no banco (nenhuma delas cresce com o volume de dados).
"""

from dataclasses import dataclass

from django.db.models import Count, QuerySet

from apps.equipment.models import Condition, Equipment, Status
from apps.maintenance.models import Maintenance, MaintenanceStatus
from apps.operations.models import Movement

# Condições que caracterizam um equipamento "que exige atenção" — mesmas
# duas piores opções de `Condition` (nenhuma nova categoria inventada).
_ATTENTION_CONDITIONS = (Condition.RUIM, Condition.INUTILIZAVEL)

# Quantos itens cada lista da Home mostra — pequeno de propósito (a Home é
# uma visão geral, não uma listagem completa; cada seção linka para a
# listagem real correspondente, que já pagina).
_RECENT_LIST_LIMIT = 5


@dataclass(frozen=True)
class HomeStatusCounts:
    disponiveis: int
    em_operacao: int
    em_manutencao: int


def get_equipment_status_counts() -> HomeStatusCounts:
    """
    UMA consulta agregada (`GROUP BY status`) — não três `.count()`
    separados. Só equipamento ATIVO conta (SoftDeleteModel não filtra
    isso automaticamente por padrão — ver apps/core/models.py).
    """

    rows = (
        Equipment.objects.filter(is_active=True)
        .values("status")
        .annotate(total=Count("id"))
    )
    counts = {row["status"]: row["total"] for row in rows}
    return HomeStatusCounts(
        disponiveis=counts.get(Status.DISPONIVEL, 0),
        em_operacao=counts.get(Status.EM_OPERACAO, 0),
        em_manutencao=counts.get(Status.MANUTENCAO, 0),
    )


def get_open_maintenance_count() -> int:
    """
    Card "Manutenções abertas" — contagem de FICHAS de manutenção em
    aberto (`Maintenance`, domínio técnico), distinta do card "Em
    manutenção" acima (que é `Equipment.status`, domínio operacional). As
    duas podem divergir (ex.: manutenção em campo sem mudança de status) —
    é intencional, cada uma responde uma pergunta diferente (auditoria,
    item [27]).

    Backed pela mesma partial `UniqueConstraint` que já garante no máximo
    uma manutenção aberta e ativa por equipamento — este `.count()` é
    barato e não corre risco de N+1 (não está dentro de laço nenhum).
    """

    return Maintenance.objects.filter(status=MaintenanceStatus.ABERTA, is_active=True).count()


def get_recent_movements(limit: int = _RECENT_LIST_LIMIT) -> QuerySet[Movement]:
    """
    `Movement` já denormaliza os nomes de origem/destino/cliente em campos
    próprios (`origin_location_name`, etc.) — `select_related("equipment")`
    é o único JOIN necessário para o template não disparar uma query por
    linha ao acessar `movement.equipment.patrimonio`.
    """

    return Movement.objects.select_related("equipment").order_by("-created_at")[:limit]


def get_open_maintenances(limit: int = _RECENT_LIST_LIMIT) -> QuerySet[Maintenance]:
    return (
        Maintenance.objects.filter(status=MaintenanceStatus.ABERTA, is_active=True)
        .select_related("equipment", "equipment__model")
        .order_by("-created_at")[:limit]
    )


def get_equipment_needing_attention(limit: int = _RECENT_LIST_LIMIT) -> QuerySet[Equipment]:
    """"Equipamentos que exigem atenção" — condição Ruim ou Inutilizável, ainda ativos."""

    return (
        Equipment.objects.filter(is_active=True, condition__in=_ATTENTION_CONDITIONS)
        .select_related("model")
        .order_by("-updated_at")[:limit]
    )


def build_home_context() -> dict:
    """
    Monta o contexto completo da Home numa única chamada — 5 consultas ao
    todo (1 agregação de status + 1 contagem de manutenções abertas + 3
    slices limitados), nenhuma delas repetida por item de lista (auditoria,
    item [28]: "a quantidade de queries não pode crescer proporcionalmente
    à quantidade de registros").
    """

    status_counts = get_equipment_status_counts()
    return {
        "status_counts": status_counts,
        "open_maintenance_count": get_open_maintenance_count(),
        "recent_movements": get_recent_movements(),
        "open_maintenances": get_open_maintenances(),
        "equipment_needing_attention": get_equipment_needing_attention(),
    }
