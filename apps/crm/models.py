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

from decimal import Decimal

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


# ---------------------------------------------------------------------------
# Produtos e Serviços / Proposta Comercial + Contrato (implementação
# completa, 14/09/2026 — ver especificação "LOCUSHUB — CRM / IMPLEMENTAÇÃO
# COMPLETA DA ABA 'PRODUTOS E SERVIÇOS'"). Auditoria feita antes de
# codificar (seção 0 da especificação): `Category`/`EquipmentModel`
# reaproveitados de `apps.catalog` (nunca uma segunda lista de
# equipamentos dentro do CRM — seção 9); `Client`/`Address` continuam
# exclusivamente de `apps.clients`/`apps.core` (seção 37); numeração seue
# o MESMO padrão de `apps.equipment.services.create_equipment()`
# (contador dedicado + `select_for_update()`, nunca MAX(id)+1 — seção 82,
# ver `NumberingCounter`/`apps.crm.services._next_document_number()`).
#
# Modelagem final (nomes auditados contra a arquitetura real, seção 52):
#   Proposal        — identidade da proposta dentro da Opportunity.
#   ProposalVersion — "fotografia" comercial imutável assim que emitida:
#                      condições, período, logística, financeiro, textos
#                      e os snapshots de cliente/Locus (seção 54).
#   ProposalItem    — produto/modelo + quantidade + preço + desconto
#                      daquela versão (seção 55).
#   Contract        — documento contratual derivado de UMA ProposalVersion
#                      (seção 63/67).
#
# Decisão de produto registrada (seção 53: "Não assumir exatamente esses
# campos sem auditar" — `Proposal.status` NÃO foi criado como campo
# armazenado. Um `status` gravado em `Proposal`, ao lado do `status` já
# necessário em cada `ProposalVersion` (rascunho/emitida/aceita), seria
# EXATAMENTE a "duas fontes conflitantes" que a própria especificação
# probe em outro ponto (seção 75, sobre `closed_value`) — qual dos dois
# venceria se divergissem? `Proposal.status` é sempre DERIVADO da versão
# mais recente (`Proposal.latest_version`/`Proposal.display_status`
# abaixo), nunca uma segunda gravação.
# ---------------------------------------------------------------------------


class NumberingCounter(models.Model):
    """
    Contador dedicado para numeração seura de documentos (seção 82: "Não
    usar MAX(id)+1 sem proteção") — mesmo raciocínio de
    `EquipmentModel.last_sequence`: uma linha pequena e dedicada, travada
    via `select_for_update()` dentro de uma transação
    (`apps.crm.services._next_document_number()`), nunca contado a partir
    da própria tabela de destino (`Proposal`/`Contract`), o que exigiria
    travar a tabela inteira ou arriscar corrida entre o SELECT e o
    INSERT.
    """

    key = models.CharField(max_length=30, unique=True)
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "contador de numeração"
        verbose_name_plural = "contadores de numeração"

    def __str__(self) -> str:
        return f"{self.key}: {self.last_value}"


class PaymentMethod(models.TextChoices):
    """
    Forma de pagamento — seção 30: "Não hardcodar a arquitetura para
    somente [PIX/Boleto/Cartão]." Auditoria confirmou que não existe
    nenhuma estrutura equivalente já no projeto — `TextChoices` pequeno e
    fechado (não uma entidade configurável como `CommercialSource`,
    seria over-engineering para 5 opções conceitualmente estáveis), com
    `OUTRO` + `payment_method_other` texto livre como válvula de escape
    (mesmo padrão já usado em `MovementType.OUTRO`/`Movement.reason`).
    """

    PIX = "PIX", "PIX"
    BOLETO = "BOLETO", "Boleto"
    CARTAO = "CARTAO", "Cartão"
    TRANSFERENCIA = "TRANSFERENCIA", "Transferência bancária"
    OUTRO = "OUTRO", "Outro"


class ProposalVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Rascunho"
    ISSUED = "ISSUED", "Emitida"
    ACCEPTED = "ACCEPTED", "Aceita"


class Proposal(TimeStampedModel):
    """
    Identidade da proposta comercial dentro da Opportunity (seção 53) —
    o "número" (`PROP-000123`) e a relação com a Opportunity. Toda a
    substância comercial (condições/itens/financeiro/textos) vive em
    `ProposalVersion` — `Proposal` nunca é editada diretamente por
    nenhuma tela (ver `apps.crm.services`).
    """

    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="proposals")
    number = models.CharField(max_length=20, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="proposals_created")

    class Meta:
        verbose_name = "proposta"
        verbose_name_plural = "propostas"
        ordering = ["-created_at"]
        permissions = [
            ("issue_proposal_documents", "Pode emitir documentos de proposta (Proposta Comercial)"),
        ]

    @property
    def latest_version(self) -> "ProposalVersion | None":
        return self.versions.order_by("-version_number").first()

    @property
    def display_status(self) -> str:
        """Status DERIVADO da versão mais recente — nunca uma segunda gravação (ver nota do módulo)."""
        latest = self.latest_version
        return latest.get_status_display() if latest else "Sem versão"

    def __str__(self) -> str:
        return self.number


class ProposalVersion(TimeStampedModel):
    """
    "Fotografia" comercial de uma negociação em um momento — a unidade
    real de versionamento (seção 54/59/60). `status=DRAFT` pode ser
    editada livremente (seção 56); `ISSUED`/`ACCEPTED` são imutáveis —
    a imutabilidade é garantida em `apps.crm.services` (toda função de
    escrita rejeita `status != DRAFT`), não só por convenção de UI.

    Snapshots (`client_*_snapshot`/`company_*_snapshot`) ficam em branco
    enquanto `DRAFT` (o rascunho consulta `Opportunity.client`/
    `apps.core.services.get_company_profile()` AO VIVO para exibição) e
    são preenchidos uma única vez, em `issue_proposal()`, no momento da
    emissão (seção 21/38/39) — depois disso, o PDF de uma versão emitida
    nunca mais consulta `Client`/`CompanyProfile` ao vivo.
    """

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=ProposalVersionStatus.choices, default=ProposalVersionStatus.DRAFT)

    # --- Condições comerciais (seção 4/30/31) ---------------------------
    price_table_label = models.CharField(
        max_length=100,
        blank=True,
        help_text="Texto livre por enquanto — ponto de extensão para a futura PriceTable (seção 19/102, não implementada nesta etapa).",
    )
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, blank=True)
    payment_method_other = models.CharField(
        max_length=100, blank=True, help_text="Usado quando 'Forma de pagamento' = Outro."
    )
    payment_condition = models.CharField(
        max_length=150, blank=True, help_text="Ex.: 'À vista', '28 dias' — texto livre (seção 31)."
    )

    # --- Período contratado / logística (seção 42-51) --------------------
    contracted_start_date = models.DateField(null=True, blank=True)
    contracted_end_date = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    expected_delivery_time = models.TimeField(null=True, blank=True)
    expected_pickup_date = models.DateField(null=True, blank=True)
    expected_pickup_time = models.TimeField(null=True, blank=True)
    # Local de entrega/operação — Location real (seção 41), NUNCA
    # sobrescreve o endereço fiscal do Client.
    delivery_location = models.ForeignKey(
        "operations.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="proposal_versions",
    )

    # --- Resumo financeiro (seção 24-29, Decimal sempre, nunca float) ----
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    general_discount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"), help_text="Valor monetário, não percentual (seção 25)."
    )
    interest_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"), help_text="Juros (seção 26).")
    freight_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # --- Textos (seção 32-34) --------------------------------------------
    special_clauses = models.TextField(blank=True)
    payment_info_notes = models.TextField(blank=True)
    general_notes = models.TextField(blank=True)

    # --- Snapshot do cliente (seção 35/38) --------------------------------
    client_name_snapshot = models.CharField(max_length=200, blank=True)
    client_document_snapshot = models.CharField(max_length=20, blank=True)
    client_contact_snapshot = models.CharField(max_length=150, blank=True)
    client_phone_snapshot = models.CharField(max_length=30, blank=True)
    client_email_snapshot = models.CharField(max_length=254, blank=True)
    client_address_snapshot = models.TextField(blank=True)

    # --- Snapshot da Locus (seção 35/36/39/40) ----------------------------
    company_name_snapshot = models.CharField(max_length=200, blank=True)
    company_document_snapshot = models.CharField(max_length=20, blank=True)
    company_address_snapshot = models.TextField(blank=True)
    company_phone_snapshot = models.CharField(max_length=30, blank=True)
    company_email_snapshot = models.CharField(max_length=254, blank=True)
    seller_snapshot = models.CharField(
        max_length=150, blank=True, help_text="Responsável/vendedor (owner da Opportunity) no momento da emissão (seção 40)."
    )

    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="proposal_versions_issued"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="proposal_versions_accepted"
    )

    class Meta:
        verbose_name = "versão da proposta"
        verbose_name_plural = "versões da proposta"
        ordering = ["proposal_id", "version_number"]
        constraints = [
            models.UniqueConstraint(fields=["proposal", "version_number"], name="uniq_proposal_version_number"),
            models.CheckConstraint(check=models.Q(subtotal__gte=0), name="proposal_version_subtotal_not_negative"),
            models.CheckConstraint(check=models.Q(total__gte=0), name="proposal_version_total_not_negative"),
            models.CheckConstraint(check=models.Q(general_discount__gte=0), name="proposal_version_general_discount_not_negative"),
            models.CheckConstraint(check=models.Q(interest_amount__gte=0), name="proposal_version_interest_not_negative"),
            models.CheckConstraint(check=models.Q(freight_amount__gte=0), name="proposal_version_freight_not_negative"),
        ]
        permissions = [
            ("generate_contract", "Pode gerar contratos a partir de uma proposta"),
        ]

    @property
    def is_editable(self) -> bool:
        """Só DRAFT pode ser editada — ver docstring da classe. Checagem real fica em `apps.crm.services`, isto é só conveniência de leitura (templates)."""
        return self.status == ProposalVersionStatus.DRAFT

    def __str__(self) -> str:
        return f"{self.proposal.number} v{self.version_number}"


class ProposalItem(models.Model):
    """
    Produto/modelo comercial de uma `ProposalVersion` (seção 55). Sempre
    referencia `EquipmentModel` (o MODELO, ex. "NI23TC") — NUNCA um
    `Equipment`/patrimônio físico individual (seção 10, REGRA CRÍTICA: a
    seleção de patrimônio pertence exclusivamente à aba Equipamentos).

    `description_snapshot` é preenchido uma única vez, na criação do item
    (`apps.crm.services.add_proposal_item()`), a partir do nome/código do
    `EquipmentModel` no momento — nunca resincronizado depois. Como cada
    nova versão CLONA seus próprios itens (`create_new_version()`, nunca
    reaproveita a linha da versão anterior), isso já garante que uma
    versão emitida nunca muda de descrição por causa de uma edição
    posterior do catálogo (seção 21/62), sem precisar de nenhuma lógica
    extra de "congelamento" no momento da emissão.
    """

    proposal_version = models.ForeignKey(ProposalVersion, on_delete=models.CASCADE, related_name="items")
    equipment_model = models.ForeignKey(
        "catalog.EquipmentModel", on_delete=models.PROTECT, related_name="proposal_items"
    )
    description_snapshot = models.CharField(max_length=200, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    item_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "item da proposta"
        verbose_name_plural = "itens da proposta"
        ordering = ["order", "id"]
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name="proposal_item_quantity_positive"),
            models.CheckConstraint(check=models.Q(unit_price__gte=0), name="proposal_item_unit_price_not_negative"),
            models.CheckConstraint(
                check=models.Q(item_discount_percent__gte=0) & models.Q(item_discount_percent__lte=100),
                name="proposal_item_discount_percent_in_range",
            ),
            models.CheckConstraint(check=models.Q(line_total__gte=0), name="proposal_item_line_total_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.description_snapshot} x{self.quantity}"


class Contract(models.Model):
    """
    Documento contratual derivado de UMA `ProposalVersion` (seção 63/67)
    — entidade separada, nunca um "PDF híbrido" com a proposta (seção
    65). `on_delete=PROTECT` em `proposal_version`: um contrato já
    gerado nunca pode ficar órfão (nenhum fluxo exclui `ProposalVersion`
    de qualquer forma, mas a proteção documenta a intenção).

    `legal_text_is_placeholder` (seção 68: "NÃO inventar cláusulas
    jurídicas... Se não existir [contrato real aprovado]: implementar
    infraestrutura e documentar que o conteúdo aprovado precisa ser
    fornecido"): auditoria não encontrou nenhum template de contrato
    real/aprovado no repositório — o PDF gerado usa um texto-placeholder
    claramente identificado como tal (ver `templates/crm/pdf/contract.html`),
    nunca uma cláusula jurídica inventada. `True` até a Locus fornecer o
    texto aprovado (fora do escopo desta implementação).
    """

    proposal_version = models.ForeignKey(ProposalVersion, on_delete=models.PROTECT, related_name="contracts")
    number = models.CharField(max_length=20, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contracts_created")
    created_at = models.DateTimeField(auto_now_add=True)
    legal_text_is_placeholder = models.BooleanField(default=True)

    class Meta:
        verbose_name = "contrato"
        verbose_name_plural = "contratos"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.number
