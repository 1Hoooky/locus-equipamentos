"""
Manutenção e Higienização — fundação da próxima etapa da Fase 2, arquitetura
aprovada em 27/08/2026 (decisões 1-10 sobre a proposta original de
26/08/2026). Domínio TÉCNICO, deliberadamente separado de:

- `apps.operations` (domínio FÍSICO: onde o equipamento está —
  `Location`/`Movement`);
- `apps.equipment` (cadastro e estado corrente do equipamento).

Regra central, repetida aqui porque é a mais fácil de violar por engano:
`Movement` continua sendo a ÚNICA fonte de verdade de localização física
(`Equipment.current_location`/`current_client`). Nada neste módulo escreve
nesses dois campos, em nenhuma circunstância — só
`apps.operations.services.create_movement()` faz isso.

`Maintenance`/`Cleaning` só têm permissão para mudar `Equipment.status`/
`Equipment.condition`, e exclusivamente através dos services já existentes
de `apps.equipment.services` (`change_status()`/`change_condition()`) —
nunca atribuição direta (`equipment.status = ...`). Ver
`apps.maintenance.services` para a estratégia de restauração de status
(decisão 3) e a matriz completa de status × movimentação (decisão 4),
documentadas no topo daquele módulo antes do código.
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import User
from apps.core.models import SoftDeleteModel, TimeStampedModel
from apps.equipment.models import Condition, Equipment, Status
from apps.operations.models import Movement


class MaintenanceType(models.TextChoices):
    PREVENTIVA = "PREVENTIVA", "Preventiva"
    CORRETIVA = "CORRETIVA", "Corretiva"


class MaintenanceStatus(models.TextChoices):
    ABERTA = "ABERTA", "Aberta"
    CONCLUIDA = "CONCLUIDA", "Concluída"
    CANCELADA = "CANCELADA", "Cancelada"


class Maintenance(TimeStampedModel, SoftDeleteModel):
    """
    Evento técnico de manutenção (preventiva ou corretiva) — uma "ficha"
    que abre (`ABERTA`), e mais tarde fecha (`CONCLUIDA`/`CANCELADA`).
    Diferente de `Movement` (imutável, criado já completo), `Maintenance`
    tem ciclo de vida próprio porque diagnóstico e serviço executado
    normalmente acontecem em momentos diferentes — às vezes dias depois.
    Único caminho suportado para criar/fechar/cancelar:
    `apps.maintenance.services` (nunca `Maintenance.objects.create()`/
    `.save()` direto em view/form).

    `departure_movement`/`return_movement` são OPCIONAIS dos dois lados —
    cobrem tanto "equipamento foi fisicamente para a Location de
    manutenção" (linkado ao `Movement` `ENVIO_MANUTENCAO`/
    `RETORNO_MANUTENCAO`/`RETORNO_ESTOQUE` já existente) quanto
    "manutenção feita no local, sem o equipamento se mover". Nenhum dos
    dois é obrigatório — forçar um deles quebraria o caso legítimo de
    manutenção em campo. `unique=True` nos dois: um mesmo `Movement`
    nunca pode ser reclamado por duas `Maintenance` diferentes.

    `status_before`/`condition_before` são SNAPSHOTS determinísticos,
    capturados automaticamente por `open_maintenance()` no momento da
    abertura — nunca preenchidos por adivinhação depois.

    SEMÂNTICA EXATA de `status_before` (revisada em 27/08/2026, decisão 5
    — sem rename, só esclarecimento): é o `Equipment.status` no instante
    em que ESTA FICHA foi aberta, não "o status antes de qualquer
    manutenção" em sentido amplo. Isso importa porque os dois casos são
    diferentes:

    - SEM `departure_movement` (Maintenance é quem muda o status): aqui
      `status_before` É o valor a restaurar — captura o status genuíno
      de antes de `change_status(MANUTENCAO)` rodar, dentro da mesma
      chamada de `open_maintenance()`.
    - COM `departure_movement` (o Movement ENVIO_MANUTENCAO já rodou
      antes): `status_before` é só `MANUTENCAO` (o que já valia quando a
      ficha foi aberta) — não representa "o status antes do envio físico"
      e NUNCA é usado para restaurar nada nesse caso (ver
      `_restore_status_if_owned()`, que curto-circuita sempre que
      `departure_movement_id is not None`). Se algum dia for preciso
      saber o status genuíno anterior ao envio físico, a fonte correta é
      `StatusHistory`/`Movement` anteriores a `departure_movement.created_at`
      — nunca este campo.

    Em outras palavras: `status_before` é "o que capturar na abertura
    para permitir desfazer, SE for esta ficha quem fez a mudança" — nunca
    "o histórico verdadeiro de status anterior à manutenção" em geral.
    Ver `apps.maintenance.services._restore_status_if_owned()` para a
    lógica completa, incluindo o caso de corrida (`Movement` externo já
    mudou o status enquanto a manutenção seguia aberta).
    """

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="maintenances")
    maintenance_type = models.CharField(max_length=20, choices=MaintenanceType.choices)
    status = models.CharField(max_length=20, choices=MaintenanceStatus.choices, default=MaintenanceStatus.ABERTA)

    # Preenchido na abertura (o que motivou/o que se espera fazer).
    diagnosis = models.TextField(blank=True)
    # Preenchido só no fechamento — exigido para concluir (ver constraint).
    service_performed = models.TextField(blank=True)

    # Snapshots narrativos do próprio registro de manutenção — não são a
    # fonte de verdade de "condição atual" (essa é sempre
    # `ConditionHistory`, via `change_condition()`); mesmo padrão que
    # `Movement` já usa com seus campos `*_name` ao lado das FKs vivas.
    condition_before = models.CharField(max_length=20, choices=Condition.choices, blank=True)
    condition_after = models.CharField(max_length=20, choices=Condition.choices, blank=True)

    # Snapshot determinístico p/ restauração de status — ver docstring da
    # classe (semântica exata, revisada em 27/08/2026) e
    # `apps.maintenance.services._restore_status_if_owned()`.
    status_before = models.CharField(
        max_length=20,
        choices=Status.choices,
        blank=True,
        help_text=(
            "Status do equipamento no instante em que ESTA FICHA foi aberta — usado para restaurar "
            "só quando departure_movement é nulo (esta ficha é dona da transição). Com "
            "departure_movement preenchido, este campo vale MANUTENCAO e é apenas informativo "
            "(o status genuinamente anterior, se precisar, está em StatusHistory/Movement)."
        ),
    )

    # OneToOneField (não ForeignKey(unique=True)) — a própria semântica é
    # "no máximo uma Maintenance por Movement"; Django recomenda
    # OneToOneField nesse caso (fields.W342).
    departure_movement = models.OneToOneField(
        Movement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="maintenance_as_departure",
        help_text="Movement ENVIO_MANUTENCAO associado, quando a manutenção envolveu saída física do equipamento.",
    )
    return_movement = models.OneToOneField(
        Movement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="maintenance_as_return",
        help_text="Movement de retorno (RETORNO_MANUTENCAO ou RETORNO_ESTOQUE) associado, quando houver.",
    )

    responsible = models.ForeignKey(User, on_delete=models.PROTECT, related_name="maintenances_responsible")
    notes = models.TextField(blank=True)

    # Informativo apenas — sem motor de recorrência (decisão 9: este
    # campo é a última data planejada conhecida, não uma regra de
    # repetição; ver services.py para a análise completa).
    next_due_at = models.DateField(null=True, blank=True)

    closed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="maintenances_created")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "manutenção"
        verbose_name_plural = "manutenções"
        ordering = ["-created_at"]
        constraints = [
            # Mesmo raciocínio de `movement_outro_requires_reason`
            # (apps.operations.models.Movement): não é possível concluir
            # sem registrar o que foi feito.
            models.CheckConstraint(
                check=~models.Q(status=MaintenanceStatus.CONCLUIDA) | ~models.Q(service_performed=""),
                name="maintenance_conclusao_exige_servico",
            ),
            # closed_at preenchido se e somente se a manutenção não está
            # mais aberta — impede o estado impossível "concluída/
            # cancelada sem data de fechamento" ou "aberta com data de
            # fechamento já registrada".
            models.CheckConstraint(
                check=(
                    models.Q(status=MaintenanceStatus.ABERTA, closed_at__isnull=True)
                    | (~models.Q(status=MaintenanceStatus.ABERTA) & models.Q(closed_at__isnull=False))
                ),
                name="maintenance_closed_at_coerente_com_status",
            ),
            # No máximo UMA manutenção ABERTA E ATIVA por equipamento ao
            # mesmo tempo — impede o estado impossível de duas fichas
            # abertas disputando o mesmo `status_before`/restauração.
            # `is_active=True` é deliberado (ajuste de 27/08/2026,
            # decisão 4): `Maintenance` herda `SoftDeleteModel`, e uma
            # ficha inativada (`is_active=False` — ex.: cadastrada por
            # engano) NUNCA deve prender o equipamento indefinidamente
            # atrás de uma constraint de banco; só uma ficha ATIVA e
            # ABERTA conta como "aberta" de verdade. Reforçada também em
            # `open_maintenance()`/`apps.maintenance.services.has_open_maintenance()`
            # com a MESMA condição, para uma mensagem clara — mesma dupla
            # camada já usada em `_validate_location_client_matches_type()`.
            models.UniqueConstraint(
                fields=["equipment"],
                condition=models.Q(status=MaintenanceStatus.ABERTA, is_active=True),
                name="uniq_maintenance_aberta_ativa_por_equipamento",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.equipment.patrimonio}: {self.get_maintenance_type_display()} ({self.get_status_display()})"


class Cleaning(TimeStampedModel, SoftDeleteModel):
    """
    Evento técnico de higienização — ATÔMICO, sem ciclo aberta/concluída
    (decisão 5): diferente de `Maintenance`, uma higienização normalmente
    não tem a separação temporal "diagnóstico hoje, serviço executado
    depois" — é uma visita única, registrada já completa. Por isso se
    parece mais com `Movement` (evento imutável) do que com `Maintenance`
    (ficha com estado).

    Sem `HistoricalRecords()` de propósito: não há "mudança de estado"
    para historiar. Nenhum campo é editado depois de criado — corrigir um
    registro errado é `is_active=False` (via
    `apps.maintenance.services.cancel_cleaning()`) seguido de um novo
    registro correto, nunca `UPDATE` do existente (decisão 10: "evitando
    UPDATE silencioso após registrado").

    `movement` é opcional — só quando a higienização coincidiu com uma
    movimentação física relevante (ex.: equipamento higienizado ao
    retornar ao estoque). Nunca obrigatório: a maior parte das
    higienizações acontece sem nenhuma movimentação.

    Cleaning NÃO altera `Equipment.status`/`condition` automaticamente
    (decisão 5) — higienizar não muda a condição operacional do
    equipamento por si só.
    """

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="cleanings")
    performed_at = models.DateTimeField()
    responsible = models.ForeignKey(User, on_delete=models.PROTECT, related_name="cleanings_responsible")
    notes = models.TextField(blank=True)

    # Mesma ressalva de `Maintenance.next_due_at` — informativo, sem
    # motor de recorrência (decisão 9).
    next_due_at = models.DateField(null=True, blank=True)

    movement = models.ForeignKey(
        Movement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cleanings",
        help_text="Movement associado, quando a higienização coincidiu com uma movimentação física relevante.",
    )

    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="cleanings_created")

    class Meta:
        verbose_name = "higienização"
        verbose_name_plural = "higienizações"
        ordering = ["-performed_at"]

    def __str__(self) -> str:
        return f"{self.equipment.patrimonio}: higienização em {self.performed_at:%d/%m/%Y}"
