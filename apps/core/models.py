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


class ConsumedSubmissionToken(models.Model):
    """
    Chave de idempotência de formulário — 3º reteste manual: o consumo do
    token de reenvio só na SESSÃO tinha uma race condition real (dois
    POSTs quase simultâneos carregam a mesma sessão no início do request,
    ambos veem o token na própria cópia em memória, ambos passam na
    checagem e ambos criam — o `del` de um não afeta a cópia já carregada
    do outro, porque a sessão só é persistida no fim do request).

    A atomicidade agora vem do banco: consumir um token é INSERIR uma
    linha aqui, e o índice UNIQUE de `token` garante que, de N requisições
    concorrentes com o MESMO token, exatamente UMA consegue inserir — as
    demais recebem IntegrityError e são tratadas como reenvio. PostgreSQL
    serializa os inserts conflitantes no próprio índice, sem lock manual.

    As linhas são um registro de consumo, não de emissão: só tokens já
    usados chegam aqui. `created_at` permite expurgo periódico (qualquer
    linha com mais de alguns dias já não corresponde a nenhum formulário
    aberto — o token da sessão terá sido substituído muito antes);
    `SubmissionGuard.issue()` faz esse expurgo de forma oportunista.
    """

    token = models.CharField(max_length=64, unique=True)
    scope = models.CharField(max_length=150, help_text="Só para diagnóstico — qual formulário consumiu o token.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "token de submissão consumido"
        verbose_name_plural = "tokens de submissão consumidos"

    def __str__(self) -> str:
        return f"{self.scope}: {self.token[:8]}…"


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


class CompanyProfile(TimeStampedModel):
    """
    Dados cadastrais da própria Locus ("DADOS DO CONTRATADO") — criado
    para a implementação de Produtos e Serviços/Propostas do CRM
    (14/09/2026, especificação seção 36: "Auditar se existe configuração
    empresarial. Se existir: reutilizar. Se não existir: criar/propor
    configuração apropriada e simples. Não hardcodar informações da
    empresa em múltiplos templates.") — auditoria confirmou que NENHUMA
    configuração empresarial existia antes desta rodada (nem em
    `apps.qrcodes`, nem em nenhum outro app; só `LOCUS_*_URL` para CTAs
    da landing pública, que são links, não dados cadastrais).

    Singleton simples: sempre `pk=1`, sem tela de "criar novo" — só uma
    linha existe, editada in-place pela tela de configuração (ver
    `apps.core.services.get_company_profile()`). Não é `SoftDeleteModel`:
    não existe "desativar a própria empresa".

    Campos = exatamente o bloco "DADOS DO CONTRATADO" do documento real
    da Locus (especificação, seção 35) — nenhum campo extra especulativo.
    Endereço como texto solto (não `Address` FK): o endereço do
    CONTRATADO aqui é só para impressão no PDF da proposta/contrato,
    nunca navegado/reaproveitado como `Location`/endereço operacional —
    usar o model `Address` (pensado para CEP/logradouro/bairro
    estruturado e reuso por `Client`/`Location`) seria over-engineering
    para um dado que nunca muda de forma e nunca aparece em mais de um
    lugar.

    Snapshot: `apps.crm.models.ProposalVersion`/`Contract` NUNCA leem
    `CompanyProfile` diretamente no momento de gerar o PDF de uma versão
    já emitida — copiam os campos abaixo para os próprios campos
    `company_*_snapshot` no momento da emissão (especificação, seção 39:
    "Se os dados empresariais mudarem no futuro: documento antigo
    continua reproduzível como foi emitido"). Só o RASCUNHO consulta este
    model ao vivo, para pré-preencher o cabeçalho da futura proposta.
    """

    company_name = models.CharField(max_length=200, blank=True, help_text="Razão social/nome da empresa.")
    cnpj = models.CharField(max_length=20, blank=True)
    logradouro = models.CharField(max_length=255, blank=True)
    numero = models.CharField(max_length=20, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    uf = models.CharField(max_length=2, blank=True)
    cep = models.CharField(max_length=9, blank=True)
    phone = models.CharField(max_length=30, blank=True, help_text="Telefone fixo.")
    mobile_phone = models.CharField(max_length=30, blank=True, help_text="Celular.")
    email = models.EmailField(blank=True)

    class Meta:
        verbose_name = "dados da empresa"
        verbose_name_plural = "dados da empresa"
        # Uma única Permission de escrita — reaproveitada de
        # `crm.manage_commercial_settings` (ver apps.crm.services), nunca
        # uma Permission nova só para isto: hoje o único consumidor real
        # é a área comercial do CRM (proposta/contrato), então uma
        # segunda Permission redundante violaria "evitar excesso de
        # permissions" (especificação, seção 83). Se outro app passar a
        # escrever aqui no futuro (ex.: etiquetas com dados da empresa),
        # revisitar essa decisão.
        permissions: list[tuple[str, str]] = []

    def __str__(self) -> str:
        return self.company_name or "Dados da empresa"
