"""
Infraestrutura compartilhada de "exclusão definitiva" (hard delete) —
rodada "AMBIENTE EM DESENVOLVIMENTO / HARD DELETE DURANTE DESENVOLVIMENTO
/ NÃO FAZER CASCADE CEGO", 11/09/2026.

Contexto do pedido: o sistema ainda está em desenvolvimento e a maioria
dos registros hoje é dado de teste/homologação. A "autoridade máxima"
(aqui, `is_superuser` PURO — ver raciocínio abaixo) precisa conseguir
apagar Cliente/Equipamento/Oportunidade de teste DE VERDADE (não só
`is_active=False`), mas SEM cascatear às cegas: cada `hard_delete_*()`
(um por entidade, em `apps.clients.services`/`apps.equipment.services`/
`apps.crm.services`) só remove junto os registros que a auditoria de
relações (CASCADE/PROTECT/SET_NULL, ver relatório da rodada) classificou
como DEPENDÊNCIA EXCLUSIVA daquela entidade — nunca um REGISTRO
COMPARTILHADO. Exemplos explícitos do pedido, já garantidos pelo próprio
schema sem nenhum código novo: excluir uma Oportunidade nunca exclui o
Cliente (`Opportunity.client` é `PROTECT` — a checagem só dispara ao
tentar excluir o Cliente, nunca ao excluir a Oportunidade, então nem
precisa de tratamento aqui); excluir um Cliente nunca exclui um
Equipamento só porque ele teve relação com aquele cliente
(`Equipment.current_client` é `SET_NULL` — o Django já limpa a
referência sozinho, sem apagar o Equipamento).

Por que `is_superuser` puro (não `Role.ADMIN`/nenhuma `Permission`
concedível)
-------------------------------------------------------------------
Mesma classificação "Nível C — ações de segurança do próprio sistema" já
usada em `apps.accounts.permissions.SuperuserRequiredMixin` (gestão de
Cargos/Permissões) e documentada em
`apps.accounts.permission_catalog` (categoria C do catálogo): uma
exclusão física e irreversível de dado de negócio é, no mínimo, tão
sensível quanto editar quem pode editar o quê — não devia ficar mais
fraca. Por isso as views de hard delete reusam `SuperuserRequiredMixin`
tal como está (nenhum mixin novo), e cada `hard_delete_*()` abaixo
também confere `actor.is_superuser` DENTRO do service (defesa em
profundidade — mesmo espírito de nunca confiar só na view, já usado no
resto do projeto para validação de negócio; aqui é autorização, mas o
princípio de "duas camadas" é o mesmo). Nenhuma `Permission` nova foi
adicionada ao catálogo para isto — de propósito: uma exclusão definitiva
nunca deve virar algo concedível a um Cargo comum.

Por que NÃO usamos `SoftDeleteModel`/`is_active=False` aqui
-------------------------------------------------------------------
Essa continua sendo a via NORMAL de "excluir" (arquivar) em todo o
sistema, para todo mundo. Hard delete é uma capacidade NOVA, adicional,
mais restrita — nunca uma substituição. Nada neste módulo remove ou
altera o comportamento de soft delete existente.

O que este módulo NÃO decide
-------------------------------------------------------------------
Cada `hard_delete_*()`/`preview_*_hard_delete()` continua vivendo no
`services.py` do próprio app dono da entidade (mesma disciplina de
sempre — nenhuma escrita de negócio fora de `services.py`) — isto aqui é
só a ferramenta comum (exceção + estrutura de "prévia de impacto" +
tradução de `ProtectedError` em mensagem legível) que os três
reaproveitam, para não repetir a mesma lógica três vezes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import ProtectedError


class HardDeleteBlocked(Exception):
    """
    Levantada quando a exclusão definitiva esbarra num relacionamento
    `PROTECT` que aponta para um REGISTRO COMPARTILHADO (não um
    dependente exclusivo já mapeado) — nunca capturada para "contornar"
    silenciosamente; a mensagem lista exatamente o que está segurando a
    exclusão, para o Administrador resolver manualmente (remover/
    reatribuir) antes de tentar de novo. Isto é o oposto de "bloqueio
    excessivo": o bloqueio já existia no schema (`on_delete=PROTECT`)
    porque o dado do outro lado é de fato compartilhado/independente —
    este módulo só torna o motivo visível em vez de deixar o
    `ProtectedError` cru do Django estourar na view.
    """


class HardDeleteAuthorizationError(PermissionError):
    """Levantada quando `hard_delete_*()` é chamado por um `actor` que não é `is_superuser` — defesa em profundidade (a view já bloqueia antes de chegar aqui)."""


@dataclass(frozen=True)
class HardDeleteImpact:
    """
    Resultado de `preview_*_hard_delete()` (antes de excluir) OU de
    `hard_delete_*()` (depois de excluir, como confirmação do que
    realmente saiu) — mesma estrutura nos dois casos, para a tela de
    confirmação (`preview`) e a mensagem de sucesso (`hard_delete_*`)
    reaproveitarem o mesmo template/lógica de exibição.
    """

    target_label: str  # ex.: 'o cliente "Acme Ltda"', 'o equipamento EQP-000123'
    # nome legível (plural) -> quantidade removida/a remover JUNTO (dependentes
    # exclusivos) — nunca inclui um registro compartilhado.
    dependents: dict[str, int] = field(default_factory=dict)

    @property
    def total_dependents(self) -> int:
        return sum(self.dependents.values())


def describe_protected_error(exc: ProtectedError, *, subject: str) -> str:
    """
    Traduz `django.db.models.ProtectedError` (levantado pelo Django ao
    tentar excluir um registro ainda referenciado por `on_delete=PROTECT`)
    numa mensagem legível, agrupada por tipo de registro — nunca o
    traceback cru do Django numa tela de confirmação.
    """
    counts: dict[str, int] = {}
    for obj in exc.protected_objects:
        meta = obj._meta
        label = str(meta.verbose_name_plural) if hasattr(meta, "verbose_name_plural") else str(meta.verbose_name)
        counts[label] = counts.get(label, 0) + 1

    parts = ", ".join(f"{count} {label}" for label, count in sorted(counts.items()))
    return (
        f"Não é possível excluir definitivamente {subject}: ainda há registros COMPARTILHADOS vinculados "
        f"a ele ({parts}). Esses registros não são dependentes exclusivos — não são apagados "
        f"automaticamente. Remova ou reatribua-os manualmente e tente novamente."
    )
