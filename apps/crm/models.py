"""
LocusHub — CRM, Etapa 1: fundação comercial (auditoria/implementação de
10/09/2026).

Escopo desta etapa (ver docstring de cada model abaixo para o raciocínio
específico): Origem comercial, Etapas da oportunidade, Motivos de perda,
Oportunidade, Histórico de etapa e Atividades comerciais. Propostas,
contratos, agenda central, dashboard, financeiro, comissão, automações e
integrações externas (WhatsApp/e-mail/assinatura) ficam para etapas
futuras — não há nenhum campo aqui antecipando essas entidades ainda
inexistentes (ex.: nenhum `accepted_proposal`).

Autorização: 100% na arquitetura NOVA (`User` → Cargo/`Group` →
`Permission`, ver `apps/accounts/permission_catalog.py`) — nenhum
`Role.COMERCIAL`, nenhuma constante `CAN_*` nova, nenhuma view do CRM
checando `role` legado. `Administrador`/`is_superuser` continuam com o
bypass administrativo padrão do Django (`ModelBackend.has_perm()` retorna
`True` para `is_superuser`, sem precisar de nenhuma Permission concedida
explicitamente) — mesma "válvula de segurança operacional" já usada em
`RoleRequiredMixin`/`SuperuserRequiredMixin`.

Cliente: o CRM REUTILIZA `apps.clients.models.Client` (e, por tabela,
`apps.core.models.Address`) como fonte oficial — nenhuma cópia
(`CRMClient`/`LeadClient`/etc.) foi criada. `Opportunity.client` é uma FK
comum para o `Client` já existente; nada neste app escreve em
`Client`/`Address` (ver `apps/crm/services.py`).

Padrões seguidos (auditados no repositório atual antes de codar):
- `TimeStampedModel`/`SoftDeleteModel` (`apps.core.models`) — mesma base
  de `Client`/`Category`/`EquipmentModel`/`Location`.
- `django-simple-history` (`HistoricalRecords()`) para o snapshot
  genérico de campo a campo em `Opportunity`, IGUAL a `Client`/`Location`/
  `EquipmentModel`/`Address` — nenhum sistema de auditoria paralelo.
- Histórico ESTRUTURADO à parte (`OpportunityStageChange`) para a
  transição de etapa em si, no mesmo espírito de `StatusHistory`/
  `ConditionHistory` (`apps.equipment.models`): complementa (não
  substitui) o snapshot genérico — aqui o campo importa é
  `from_stage`/`to_stage`, sempre gravado pelo mesmo caminho
  (`apps.crm.services.change_opportunity_stage()`), nunca por edição
  direta.
- `on_delete=PROTECT` em toda FK "viva" que histórico/registro comercial
  aponta (`client`, `source`, `stage`, `loss_reason`, `owner`,
  `created_by`) — mesmo raciocínio de `Address`/`Location`/`Movement`:
  uma exclusão acidental do lado "configuração" nunca pode arrastar
  dados comerciais junto. `on_delete=CASCADE` só nas duas tabelas de
  histórico/evento que pertencem inteiramente à `Opportunity`
  (`OpportunityStageChange`, `CommercialActivity`) — mesmo padrão de
  `StatusHistory.equipment`/`ConditionHistory.equipment` (CASCADE): se a
  própria `Opportunity` dona for excluída, o histórico dela não faz
  sentido órfão. Nenhuma view desta etapa exclui `Opportunity` de
  verdade (nenhum fluxo de DELETE foi implementado) — a CASCADE aqui é
  só a mesma rede de segurança que o restante do projeto já usa para
  esse relacionamento específico "pai/detalhe", nunca um caminho real de
  perda de dado comercial no uso normal do sistema.
- Permissões "reais" (`Meta.permissions`) seguindo EXATAMENTE a
  convenção já usada em todo o catálogo: nomes distintos dos
  `add_`/`change_`/`delete_`/`view_` automáticos do Django (ex.:
  `view_clients`, não `view_client`) — aqui `view_opportunities`,
  `add_opportunities`, `change_opportunities`, `change_opportunity_stage`,
  `view_commercial_activities`, `add_commercial_activities` e
  `manage_commercial_settings`. Ver relatório da tarefa para a
  justificativa completa de cada uma e por que nenhuma permissão nova
  foi criada além destas 7.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from apps.clients.models import Client
from apps.core.models import SoftDeleteModel, TimeStampedModel

# ---------------------------------------------------------------------------
# Configuração comercial — Origem, Etapa, Motivo de perda.
#
# As três são SoftDeleteModel (nunca hard delete): "não excluir fisicamente
# origem/etapa/motivo já utilizado — preferir desativação" é requisito
# explícito do pedido. Nenhuma das três foi semeada com dados definitivos
# por migration (ver relatório — decisão de produto pendente, "não inventar
# nomes definitivos"): nascem como infraestrutura vazia, configurável pelo
# Administrador via `manage_commercial_settings`.
# ---------------------------------------------------------------------------


class CommercialSource(TimeStampedModel, SoftDeleteModel):
    """
    Origem comercial (ex.: Google Ads, Indicação, Site) — entidade
    configurável, não um `TextChoices` fixo, para o Administrador poder
    administrar sem depender de migration/deploy (pedido explícito: "NÃO
    hardcodar essas opções em TextChoices se o objetivo for permitir
    administração futura").
    """

    name = models.CharField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0, help_text="Ordem de exibição nas listas/seletores.")

    class Meta:
        verbose_name = "origem comercial"
        verbose_name_plural = "origens comerciais"
        ordering = ["order", "name"]
        permissions = [
            # Cobre a escrita nas 3 entidades de configuração comercial
            # (Origem/Etapa/Motivo de perda) — uma única Permission, não
            # uma por entidade, mesmo raciocínio já usado em
            # `register_operations` (Movement), que cobre a escrita em
            # mais de uma entidade/app. Ver relatório para a análise de
            # "restringir só ao Administrador?" (decisão relatada, não
            # assumida em silêncio).
            ("manage_commercial_settings", "Pode gerenciar configurações comerciais (origens, etapas, motivos de perda)"),
        ]

    def __str__(self) -> str:
        return self.name


class OpportunityStage(TimeStampedModel, SoftDeleteModel):
    """
    Etapa configurável do funil comercial (ex.: Atendimento, Qualificação,
    Ganho, Perdido) — nomes/ordem 100% definidos pelo Administrador, nada
    fixo em código.

    `is_won`/`is_lost`: uma etapa pode representar o encerramento
    ganho/perdido do funil. As duas nunca podem ser `True` ao mesmo tempo
    na MESMA etapa (`clean()` abaixo + `CheckConstraint` no banco — dupla
    camada, mesmo padrão já usado em `Location`/`Movement`).

    Decisão de produto DELIBERADAMENTE NÃO tomada aqui (ver pedido: "se
    isso exigir decisão de produto não definida, não inventar — relatar
    a decisão pendente"): o sistema NÃO impõe que exista exatamente uma
    etapa ativa de ganho e uma de perda — zero, uma ou várias etapas
    `is_won=True`/`is_lost=True` são permitidas ao mesmo tempo (útil, por
    exemplo, se a Locus um dia quiser "Ganho — Locação" e "Ganho — Venda"
    como etapas de ganho distintas). A integridade que ESTE model garante
    é só a mínima segura: nenhuma etapa é as duas coisas ao mesmo tempo.
    Ver relatório para a decisão pendente completa.
    """

    name = models.CharField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0, help_text="Ordem de exibição no funil.")
    is_won = models.BooleanField(default=False, help_text="Etapa representa oportunidade GANHA.")
    is_lost = models.BooleanField(default=False, help_text="Etapa representa oportunidade PERDIDA.")

    class Meta:
        verbose_name = "etapa da oportunidade"
        verbose_name_plural = "etapas da oportunidade"
        ordering = ["order", "name"]
        constraints = [
            models.CheckConstraint(
                check=~(models.Q(is_won=True) & models.Q(is_lost=True)),
                name="crm_stage_not_won_and_lost_simultaneously",
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_won and self.is_lost:
            raise ValidationError("Uma etapa não pode ser simultaneamente de ganho e de perda.")

    def __str__(self) -> str:
        return self.name


class LossReason(TimeStampedModel, SoftDeleteModel):
    """Motivo de perda configurável (ex.: Preço, Concorrência, Prazo)."""

    name = models.CharField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0, help_text="Ordem de exibição nas listas/seletores.")

    class Meta:
        verbose_name = "motivo de perda"
        verbose_name_plural = "motivos de perda"
        ordering = ["order", "name"]

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Oportunidade
# ---------------------------------------------------------------------------


class BusinessType(models.TextChoices):
    """
    Tipo de negócio — conjunto fechado e pequeno (as 3 linhas de negócio
    da Locus), por isso `TextChoices` normal (diferente de Origem/Etapa/
    Motivo, que são entidades configuráveis): não há pedido de
    administração destes 3 valores pela interface, e a lista é
    conceitualmente estável. Nenhuma regra FINANCEIRA de proposta é
    implementada a partir daqui nesta etapa (pedido explícito) — é só um
    campo informativo/filtro por enquanto.
    """

    LOCACAO = "LOCACAO", "Locação"
    VENDA = "VENDA", "Venda"
    SERVICO = "SERVICO", "Serviço"


class Opportunity(TimeStampedModel):
    """
    Oportunidade comercial — entidade principal desta etapa.

    Não é `SoftDeleteModel`: nenhum fluxo de "excluir"/"desativar"
    oportunidade foi pedido ou implementado nesta etapa (só criar,
    editar, mudar etapa, ganhar, perder) — sem uso real do campo, um
    `is_active` aqui seria estado morto. Se um fluxo de exclusão/
    arquivamento for pedido numa etapa futura, adiciona-se então.

    `client` aponta para o `Client` já existente do módulo de Clientes —
    nunca uma cópia. Nada aqui sobrescreve CNPJ/endereço/nome/contato do
    `Client`; editar esses dados continua sendo exclusivamente
    `apps.clients` (ver `apps/crm/services.py`, que nunca escreve em
    `Client`).

    `owner` (responsável comercial) é um `User` real do sistema — nunca
    uma tabela paralela de vendedores. A elegibilidade de quem PODE ser
    `owner` é decidida em `apps.crm.services.eligible_owner_queryset()`
    (implementação conservadora: só usuários com a permissão de criar
    oportunidades, ou superusuário — ver relatório).

    Estado ganho/perda: `won_at`/`lost_at` nunca ambos preenchidos ao
    mesmo tempo (constraint abaixo + garantido por
    `apps.crm.services.change_opportunity_stage()`, nunca editado direto
    pela tela). `loss_reason`/`loss_notes`/`closed_value` seguem a mesma
    regra — sempre escritos/limpos em conjunto pelo service, nunca por
    edição solta de campo.

    NÃO existe (ainda) `accepted_proposal`: a entidade `Proposal` só
    chega numa etapa futura — esta FK só será criada quando `Proposal`
    existir de verdade (pedido explícito: nada de gambiarra antecipando
    entidade inexistente).
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="opportunities")
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="commercial_opportunities_owned",
        help_text="Responsável comercial pela oportunidade.",
    )
    source = models.ForeignKey(CommercialSource, on_delete=models.PROTECT, related_name="opportunities")
    business_type = models.CharField(max_length=10, choices=BusinessType.choices)
    stage = models.ForeignKey(OpportunityStage, on_delete=models.PROTECT, related_name="opportunities")

    expected_close_date = models.DateField(null=True, blank=True)
    estimated_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="Valor estimado (Decimal — nunca float)."
    )
    notes = models.TextField(blank=True)

    loss_reason = models.ForeignKey(
        LossReason, on_delete=models.PROTECT, related_name="opportunities", null=True, blank=True
    )
    loss_notes = models.TextField(blank=True)
    won_at = models.DateTimeField(null=True, blank=True)
    lost_at = models.DateTimeField(null=True, blank=True)
    closed_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Valor efetivo no fechamento (ganho) — Decimal, nunca float.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commercial_opportunities_created"
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "oportunidade"
        verbose_name_plural = "oportunidades"
        ordering = ["-created_at"]
        constraints = [
            # Rede de segurança no banco — a garantia de fato é
            # `apps.crm.services.change_opportunity_stage()`, que sempre
            # limpa o estado incompatível dentro da mesma transação.
            models.CheckConstraint(
                check=~(models.Q(won_at__isnull=False) & models.Q(lost_at__isnull=False)),
                name="crm_opportunity_not_won_and_lost_simultaneously",
            ),
            models.CheckConstraint(
                check=models.Q(estimated_value__isnull=True) | models.Q(estimated_value__gte=0),
                name="crm_opportunity_estimated_value_not_negative",
            ),
            models.CheckConstraint(
                check=models.Q(closed_value__isnull=True) | models.Q(closed_value__gte=0),
                name="crm_opportunity_closed_value_not_negative",
            ),
        ]
        permissions = [
            ("view_opportunities", "Pode ver oportunidades"),
            ("add_opportunities", "Pode criar oportunidades"),
            ("change_opportunities", "Pode editar oportunidades"),
            ("change_opportunity_stage", "Pode alterar etapa/ganho/perda de oportunidades"),
        ]

    def clean(self):
        super().clean()
        if self.estimated_value is not None and self.estimated_value < 0:
            raise ValidationError({"estimated_value": "Valor estimado não pode ser negativo."})
        if self.closed_value is not None and self.closed_value < 0:
            raise ValidationError({"closed_value": "Valor de fechamento não pode ser negativo."})
        if self.won_at and self.lost_at:
            raise ValidationError("Uma oportunidade não pode estar ganha e perdida ao mesmo tempo.")

    def __str__(self) -> str:
        return f"{self.title} ({self.client.display_name()})"


class OpportunityStageChange(models.Model):
    """
    Histórico ESTRUTURADO e append-only de mudança de etapa — mesmo
    espírito de `StatusHistory`/`ConditionHistory` (apps.equipment.models):
    nunca editado nem excluído por nenhuma view/usuário comum, sempre
    criado pelo mesmo caminho único
    (`apps.crm.services.change_opportunity_stage()`).

    `from_stage` é nulável só para a PRIMEIRA transição registrada (a
    etapa inicial na criação da oportunidade não tem "de onde veio") —
    todas as demais linhas sempre têm as duas pontas preenchidas.
    """

    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="stage_changes")
    from_stage = models.ForeignKey(
        OpportunityStage, on_delete=models.PROTECT, related_name="stage_changes_from", null=True, blank=True
    )
    to_stage = models.ForeignKey(OpportunityStage, on_delete=models.PROTECT, related_name="stage_changes_to")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="crm_stage_changes")
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True, help_text="Observação/motivo opcional da transição.")

    class Meta:
        verbose_name = "histórico de etapa"
        verbose_name_plural = "histórico de etapas"
        ordering = ["-changed_at"]

    def __str__(self) -> str:
        origin = self.from_stage.name if self.from_stage else "(criação)"
        return f"{self.opportunity_id}: {origin} → {self.to_stage.name}"


# ---------------------------------------------------------------------------
# Atividades comerciais
# ---------------------------------------------------------------------------


class ActivityType(models.TextChoices):
    LIGACAO = "LIGACAO", "Ligação"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    EMAIL = "EMAIL", "E-mail"
    REUNIAO = "REUNIAO", "Reunião"
    VISITA = "VISITA", "Visita"
    OBSERVACAO = "OBSERVACAO", "Observação"
    FOLLOW_UP = "FOLLOW_UP", "Follow-up"
    OUTRO = "OUTRO", "Outro"


class CommercialActivity(models.Model):
    """
    Registro de interação/próximo passo de uma oportunidade — SOMENTE
    registro nesta etapa (pedido explícito: nada de integração real de
    WhatsApp/e-mail).

    `scheduled_for` existe para uma futura Agenda Central poder consumir
    estas atividades — nenhuma Agenda é criada nesta etapa, só o campo
    que a alimentará depois.

    Sem `HistoricalRecords`/edição nesta etapa: o escopo pedido é
    "registrar" atividades (criar) e "visualizar" — nenhuma tela de
    editar/excluir atividade foi implementada, então um histórico de
    edição de campo não teria nenhum caminho de escrita para capturar.
    Se um fluxo de edição for pedido numa etapa futura, adiciona-se
    `HistoricalRecords()` então (mesmo raciocínio já usado no projeto
    para não criar infraestrutura sem uso real).
    """

    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=20, choices=ActivityType.choices)
    description = models.TextField(blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True, help_text="Quando a interação de fato aconteceu.")
    scheduled_for = models.DateTimeField(
        null=True, blank=True, help_text="Próximo passo agendado — consumido pela futura Agenda Central."
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="commercial_activities_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "atividade comercial"
        verbose_name_plural = "atividades comerciais"
        ordering = ["-created_at"]
        permissions = [
            ("view_commercial_activities", "Pode ver atividades comerciais"),
            ("add_commercial_activities", "Pode registrar atividades comerciais"),
        ]

    def __str__(self) -> str:
        return f"{self.opportunity_id}: {self.get_activity_type_display()}"
