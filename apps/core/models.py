"""
Modelos base compartilhados por todo o projeto.

Nenhum dado real deve ser excluído fisicamente quando tiver valor de
histórico (regra de negócio da especificação, seção 5). `SoftDeleteModel`
existe justamente para isso: "excluir" um registro só marca `is_active =
False`, nunca remove a linha do banco.
"""

from django.db import models
from simple_history.models import HistoricalRecords


class TimeStampedModel(models.Model):
    """Adiciona `created_at`/`updated_at` automáticos a qualquer modelo."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """
    Marca de inativação em vez de exclusão física.

    Importante: isto NÃO troca o manager padrão por um que filtra
    automaticamente `is_active=True` — cada app decide explicitamente,
    nas suas próprias querysets/views, se quer ver só ativos ou tudo.
    Um manager "mágico" que esconde inativos por padrão é uma fonte
    clássica de bugs sutis (ex.: relatório que "some" com equipamentos).
    """

    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True


class Address(TimeStampedModel):
    """
    Endereço reutilizável — Fase 2 (Operação, fundação aprovada em
    25/08/2026, arquitetura v1.0 + delta v1.1).

    Um único model, usado tanto pelo endereço fiscal de `Client`
    (`Client.fiscal_address`) quanto pelo endereço operacional de cada
    `Location` (`Location.address`) — nunca a mesma linha compartilhada
    entre os dois: cada `OneToOneField` aponta para seu próprio registro
    `Address`, mesmo quando os valores nasceram copiados um do outro (via
    "usar endereço fiscal como endereço de entrega" no cadastro). Isso é
    o que garante que editar um endereço depois nunca altera o outro
    silenciosamente (v1.0, seção 6).

    `reference_notes` só é usado por endereços operacionais ("portão
    azul, fundos") — fica em branco para endereço fiscal, que vem de
    registro oficial, não de referência de entrega.

    `on_delete=PROTECT` nos dois lados que apontam para cá (não
    `CASCADE`): uma exclusão acidental de `Address` nunca deve arrastar o
    `Client`/`Location` dono junto (delta v1.1, seção 5). Nenhum fluxo do
    sistema exclui um `Address` diretamente — edição é sempre update in
    place (`address.campo = valor; address.save()`).

    Tem seu próprio `HistoricalRecords()` (delta v1.1, seção 5): o
    histórico de `Client`/`Location` não captura edição feita diretamente
    no `Address` relacionado, porque a linha do `Client`/`Location` em si
    não muda quando só o endereço apontado é editado — mesmo padrão já
    usado para `EquipmentModel`/`Equipment` (dois históricos
    independentes, não um "unificado").
    """

    cep = models.CharField(max_length=9, blank=True)
    logradouro = models.CharField(max_length=255, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    complemento = models.CharField(max_length=100, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    uf = models.CharField(max_length=2, blank=True)
    reference_notes = models.TextField(blank=True, help_text="Só usado em endereços operacionais (ex.: ponto de referência).")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "endereço"
        verbose_name_plural = "endereços"

    def __str__(self) -> str:
        parts = [p for p in (self.logradouro, self.numero, self.cidade, self.uf) if p]
        return ", ".join(parts) if parts else f"Endereço #{self.pk}"
