"""
Cliente — especificação, seção 6 e 8; evoluído na Fase 2 (Operação,
arquitetura aprovada em 25/08/2026, v1.0 + delta v1.1).

O schema básico já entrava na Fase 1 (porque `Equipment.current_client`
precisa apontar para algum lugar), mas o uso operacional pleno chega
agora. Este model não vira CRM (v1.0, seção 1: "não transformar essa
etapa em CRM") — é cadastro e operação: dados cadastrais, endereço
fiscal, unidades. Nada de funil de vendas, interações, tarefas etc.
"""

from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from apps.clients.validators import validate_document_for_type
from apps.core.models import Address, SoftDeleteModel, TimeStampedModel


class ClientType(models.TextChoices):
    PJ = "PJ", "Pessoa Jurídica"
    PF = "PF", "Pessoa Física"


class Client(TimeStampedModel, SoftDeleteModel):
    client_type = models.CharField(max_length=2, choices=ClientType.choices, default=ClientType.PJ)

    # "document" continua genérico (não "cnpj") de propósito — client_type
    # já prepara Pessoa Física sem precisar renomear este campo depois
    # (v1.0, seção 1). Único entre não-nulos/não-vazios — protegido contra
    # duplicidade mesmo entre clientes soft-deletados (é a mesma empresa,
    # não deveria virar um segundo cadastro; ver create_client()).
    #
    # Decisão revista a pedido do usuário: o CNPJ/CPF é o dado que
    # realmente identifica o cliente de forma inequívoca — passou a ser
    # OBRIGATÓRIO (`blank=False`, o padrão do Django); a razão social virou
    # OPCIONAL (`blank=True` abaixo), o inverso do que valia antes. A
    # obrigatoriedade "de verdade" continua sendo decidida em
    # `apps.clients.services.create_client()`/`update_client()` (nunca só
    # aqui) — este `blank=False` só mantém o Django admin (que gera um
    # ModelForm automático a partir do model) consistente com a mesma
    # regra.
    document = models.CharField(
        max_length=18, help_text="CNPJ (ou, futuramente, CPF). Só dígitos, validado no backend."
    )
    company_name = models.CharField(max_length=200, blank=True, help_text="Razão social (opcional).")
    trade_name = models.CharField(max_length=200, blank=True, help_text="Nome fantasia.")
    registration_status = models.CharField(
        max_length=60, blank=True, help_text="Situação cadastral (ex.: 'ATIVA'), quando disponível pela consulta de CNPJ."
    )
    state_registration = models.CharField(max_length=20, blank=True, help_text="Inscrição estadual, se aplicável.")
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    contact_name = models.CharField(max_length=150, blank=True, help_text="Contato responsável.")
    notes = models.TextField(blank=True)

    # Campos de importação Auvo (LocusHub — importação de clientes, 08/09/2026).
    # Todos opcionais/aditivos, não afetam o cadastro manual em nada.
    #
    # `auvo_code` é o "Código" gerado automaticamente pelo Auvo para cada
    # cliente — identificador externo, único quando presente (mesma regra de
    # `document` abaixo), usado como chave de reimportação: reenviar a
    # mesma exportação do Auvo no futuro reconhece o cliente já importado
    # em vez de duplicar (ver apps.clients.import_auvo). Nunca é usado como
    # identidade cadastral principal — isso continua sendo `document`.
    auvo_code = models.CharField(
        max_length=40, blank=True, db_index=True, help_text="Código do cliente no Auvo (importação/rastreabilidade)."
    )
    # "Código externo" do Auvo — outro sistema de origem que o próprio Auvo
    # já registrava. Guardado só para rastreabilidade; nunca chave de
    # deduplicação (a planilha explicitamente não garante unicidade aqui).
    external_code = models.CharField(max_length=60, blank=True, db_index=True, help_text="Código externo (Auvo).")
    municipal_registration = models.CharField(max_length=20, blank=True, help_text="Inscrição municipal, se aplicável.")
    # Valor bruto da coluna "Contribuinte do ICMS" da planilha Auvo (ex.: "1",
    # "2"). Semântica ainda não confirmada com o usuário — não converter para
    # booleano/enum sem essa confirmação (decisão explícita, importação
    # Auvo, 08/09/2026).
    icms_taxpayer = models.CharField(max_length=60, blank=True, help_text="Contribuinte do ICMS (valor original, sem interpretação).")
    billing_email = models.EmailField(blank=True, help_text="E-mail de cobrança, se distinto do e-mail de contato.")

    fiscal_address = models.OneToOneField(
        Address, null=True, blank=True, on_delete=models.PROTECT, related_name="client_fiscal_for"
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["company_name"]
        constraints = [
            # Único entre valores não vazios — vários clientes SEM documento
            # ainda cadastrado (string vazia) não colidem entre si.
            models.UniqueConstraint(
                fields=["document"], condition=~models.Q(document=""), name="uniq_client_document_when_present"
            ),
            # Mesma regra para `auvo_code`: protege contra reimportação
            # acidental criando um segundo cliente para o mesmo registro
            # de origem, mesmo se a checagem em apps.clients.import_auvo
            # for de alguma forma contornada.
            models.UniqueConstraint(
                fields=["auvo_code"], condition=~models.Q(auvo_code=""), name="uniq_client_auvo_code_when_present"
            ),
        ]

    def clean(self):
        super().clean()
        if self.document:
            try:
                self.document = validate_document_for_type(self.document, self.client_type)
            except ValidationError as exc:
                raise ValidationError({"document": exc.message}) from exc

    def display_name(self) -> str:
        """
        Regra única de nome de exibição — reaproveitada pelos snapshots
        históricos de `Movement` (delta v1.1, seção 4). Cai para o
        documento (e por fim para o pk) quando nome fantasia/razão social
        não foram informados — agora que a razão social é opcional
        (o CNPJ passou a ser o campo obrigatório), não pode ficar em
        branco em listagens/mensagens.
        """
        return self.trade_name or self.company_name or self.document or f"Cliente #{self.pk}"

    def __str__(self) -> str:
        return self.display_name()
