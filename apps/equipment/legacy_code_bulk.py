"""
Preenchimento sequencial de código legado em lote (ferramenta
administrativa, pedida em 31/08/2026).

Contexto: unidades antigas têm um "código legado" (planilha antiga,
pré-sistema) registrado em `Equipment.legacy_code` — CharField já
existente (ver docstring de `apps/equipment/models.py`), sem constraint
de unicidade no banco e sem nenhum validador de formato hoje (confirmado
por auditoria: nenhum campo novo, nenhuma migration criada por esta
ferramenta). O usuário informa só o CÓDIGO INICIAL de um modelo; o
sistema ordena os equipamentos desse modelo pela SEQUÊNCIA OFICIAL do
patrimônio (`Equipment.model_sequence`, ascendente — é o mesmo número
embutido em `build_patrimonio()`, nunca `id`/`created_at`, nunca parsing
da string do patrimônio) e atribui códigos consecutivos, um por
equipamento, na ordem.

Deliberadamente NENHUM valor específico de modelo (ex.: "NI23BT"), de
código (ex.: "26101622101001") ou de formato (ex.: "4 dígitos") está
hardcoded neste módulo — a função recebe sempre o código inicial
COMPLETO e o trata como um inteiro sequencial só para o incremento,
preservando o formato de armazenamento original (comprimento e zeros à
esquerda) via `str.zfill` sobre o comprimento do código informado.

Duas funções públicas, com uma separação estrita entre "calcular" e
"gravar" (pedido explícito do usuário — nunca uma tela que digita e já
grava):

- `build_legacy_code_bulk_preview()`: só leitura, nunca altera o banco.
  Serve tanto a tela de prévia (GET) quanto a REVALIDAÇÃO no servidor no
  momento da confirmação (POST) — a mesma função, chamada de novo depois
  do lock, é o que garante que "o servidor é a autoridade final" e que a
  prévia nunca é confiada tal como veio do navegador.
- `apply_legacy_code_bulk_fill()`: escreve, dentro de uma única
  `transaction.atomic()`, com `select_for_update()` na linha do
  `EquipmentModel` (mesmo mecanismo de concorrência de
  `apps.equipment.services.create_equipment()`) para serializar duas
  confirmações concorrentes do MESMO modelo. Grava um `Equipment.save()`
  POR UNIDADE (nunca `bulk_update`), com `_change_reason` antes de cada
  save, para não perder o registro no django-simple-history — são
  dezenas/centenas de linhas, não milhões, então a troca de desempenho
  por rastreabilidade é a escolha certa (pedido explícito do usuário).
"""

from dataclasses import dataclass, field

from django.db import transaction

from apps.catalog.models import EquipmentModel
from apps.equipment.models import Equipment


class LegacyCodeBulkBlocked(Exception):
    """
    Levantada por `apply_legacy_code_bulk_fill()` quando a revalidação no
    servidor encontra qualquer motivo de bloqueio (prévia divergente,
    conflito, duplicidade, patrimônio não-ordenável, código inicial
    inválido). A view converte isto numa mensagem de erro re-renderizando
    a prévia — nunca deixa a exceção derrubar a request com 500.
    """

    def __init__(self, message: str, preview: "LegacyCodeBulkPreview | None" = None):
        super().__init__(message)
        self.preview = preview


# --- Estados possíveis de cada equipamento na prévia -----------------------
STATE_SEM_CODIGO = "SEM_CODIGO"
STATE_JA_PREENCHIDO = "JA_PREENCHIDO"
STATE_CONFLITO = "CONFLITO"


@dataclass
class LegacyCodeRow:
    """Uma linha da prévia: um equipamento e o código que ele receberia."""

    equipment_id: int
    patrimonio: str
    model_sequence: int
    current_legacy_code: str
    predicted_code: str
    state: str  # STATE_SEM_CODIGO | STATE_JA_PREENCHIDO | STATE_CONFLITO


@dataclass
class ExternalDuplicate:
    """
    Um código previsto para este lote que já pertence a OUTRO equipamento
    (de qualquer modelo) fora do lote — sempre bloqueante.
    """

    code: str
    existing_patrimonio: str
    target_patrimonio: str


@dataclass
class OrderingError:
    """Um equipamento do modelo cujo `model_sequence` impede uma ordenação/numeração confiável."""

    equipment_id: int
    patrimonio: str
    detail: str


@dataclass
class LegacyCodeBulkPreview:
    model_id: int
    model_name: str
    model_code: str
    seed_code: str
    seed_error: str = ""
    rows: list[LegacyCodeRow] = field(default_factory=list)
    ordering_errors: list[OrderingError] = field(default_factory=list)
    external_duplicates: list[ExternalDuplicate] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def first_code(self) -> str:
        return self.rows[0].predicted_code if self.rows else ""

    @property
    def last_code(self) -> str:
        return self.rows[-1].predicted_code if self.rows else ""

    @property
    def conflicts(self) -> list[LegacyCodeRow]:
        return [r for r in self.rows if r.state == STATE_CONFLITO]

    @property
    def pending_rows(self) -> list[LegacyCodeRow]:
        """Linhas que a execução realmente vai gravar (SEM_CODIGO) — JA_PREENCHIDO não precisa de save()."""
        return [r for r in self.rows if r.state == STATE_SEM_CODIGO]

    @property
    def updated_count(self) -> int:
        """Quantidade de equipamentos efetivamente gravados nesta execução (só as linhas SEM_CODIGO)."""
        return len(self.pending_rows)

    @property
    def internal_duplicates(self) -> list[str]:
        """
        Códigos previstos repetidos DENTRO do próprio lote. Na prática só
        pode acontecer se o código inicial "der a volta" (overflow do
        comprimento numérico) — `_validate_seed_code()` já bloqueia isso
        antes, mas o cálculo verifica de novo aqui como segunda linha de
        defesa (nunca confiar só numa camada).
        """
        seen: dict[str, int] = {}
        dupes = []
        for row in self.rows:
            seen[row.predicted_code] = seen.get(row.predicted_code, 0) + 1
        for code, count in seen.items():
            if count > 1:
                dupes.append(code)
        return dupes

    @property
    def blocked(self) -> bool:
        return bool(
            self.seed_error
            or self.ordering_errors
            or self.external_duplicates
            or self.internal_duplicates
            or self.conflicts
        )

    @property
    def block_reasons(self) -> list[str]:
        reasons = []
        if self.seed_error:
            reasons.append(self.seed_error)
        if self.ordering_errors:
            reasons.append(
                f"{len(self.ordering_errors)} equipamento(s) com patrimônio/sequência inválidos para ordenação."
            )
        if self.internal_duplicates:
            reasons.append("O código inicial informado geraria códigos repetidos dentro do próprio lote.")
        if self.external_duplicates:
            reasons.append(f"{len(self.external_duplicates)} código(s) já pertencem a outro equipamento.")
        if self.conflicts:
            reasons.append(f"{len(self.conflicts)} equipamento(s) já têm um código legado diferente do previsto.")
        return reasons


def _validate_seed_code(seed_code: str) -> tuple[int | None, int, str]:
    """
    Valida o código inicial e devolve (valor_numerico, largura, erro).
    `largura` é o comprimento EXATO do texto informado — é o que
    preserva zeros à esquerda no incremento (zfill de volta a esta
    largura), sem presumir nenhum comprimento fixo específico de modelo.
    """
    if not seed_code or not seed_code.strip():
        return None, 0, "Informe o código inicial."
    seed_code = seed_code.strip()
    if not seed_code.isdigit():
        return None, 0, "O código inicial deve conter apenas dígitos (mesma regra do campo de código legado)."
    if len(seed_code) > Equipment._meta.get_field("legacy_code").max_length:
        return None, 0, "O código inicial excede o tamanho máximo permitido para código legado."
    return int(seed_code), len(seed_code), ""


def build_legacy_code_bulk_preview(*, model_id: int, seed_code: str) -> LegacyCodeBulkPreview:
    """
    Calcula a prévia completa — NUNCA escreve no banco. Chamada tanto
    pela tela de prévia (GET) quanto, de novo, dentro de
    `apply_legacy_code_bulk_fill()` já com o lock do modelo adquirido,
    para a confirmação nunca confiar em dado vindo do navegador.
    """
    model = EquipmentModel.objects.get(pk=model_id)
    preview = LegacyCodeBulkPreview(
        model_id=model.pk,
        model_name=model.name,
        model_code=model.code,
        seed_code=seed_code,
    )

    seed_value, width, seed_error = _validate_seed_code(seed_code)
    if seed_error:
        preview.seed_error = seed_error
        return preview

    # Ordenação — SEMPRE por model_sequence ascendente (a sequência
    # oficial do patrimônio), nunca id/created_at, nunca parsing da
    # string do patrimônio. `is_active=True` segue a mesma convenção já
    # usada em todo `apps/equipment/views.py` para querysets
    # operacionais (SoftDeleteModel nunca filtra sozinho).
    equipments = list(
        Equipment.objects.filter(model_id=model.pk, is_active=True).order_by("model_sequence")
    )

    # Auditoria de ordenação: `model_sequence` é PositiveIntegerField
    # (nunca None/negativo por definição de campo) e tem constraint
    # UNIQUE por modelo no banco — mas um patrimônio vazio/corrompido
    # (ex.: dado legado inconsistente) ainda pode existir teoricamente,
    # então cada equipamento é auditado explicitamente antes de confiar
    # na ordem, em vez de presumir que o banco já garante tudo sozinho.
    seen_sequences: set[int] = set()
    for equipment in equipments:
        problems = []
        if not equipment.patrimonio:
            problems.append("patrimônio vazio")
        if equipment.model_sequence is None:
            problems.append("model_sequence ausente")
        elif equipment.model_sequence in seen_sequences:
            problems.append(f"model_sequence {equipment.model_sequence} duplicado no modelo")
        elif equipment.model_sequence < 1:
            problems.append(f"model_sequence inválido ({equipment.model_sequence})")
        if problems:
            preview.ordering_errors.append(
                OrderingError(
                    equipment_id=equipment.pk,
                    patrimonio=equipment.patrimonio or f"(sem patrimônio, id={equipment.pk})",
                    detail="; ".join(problems),
                )
            )
        if equipment.model_sequence is not None:
            seen_sequences.add(equipment.model_sequence)

    if preview.ordering_errors:
        # Patrimônio impossível de ordenar com segurança: paramos aqui,
        # sem sequer calcular códigos previstos (pedido explícito: nunca
        # executar silenciosamente, sempre relatar exatamente qual
        # equipamento causou o problema).
        return preview

    # Overflow: o maior código previsto precisa continuar cabendo na
    # mesma largura (não pode "estourar" dígitos, ex.: 99 -> 100) nem no
    # max_length do campo.
    max_length = Equipment._meta.get_field("legacy_code").max_length
    last_value = seed_value + len(equipments) - 1 if equipments else seed_value
    predicted_width = len(str(last_value))
    if predicted_width > width or predicted_width > max_length:
        preview.seed_error = (
            "O código inicial informado não comporta uma sequência deste tamanho sem perder os "
            "zeros à esquerda (o último código ultraparia o comprimento do código inicial)."
        )
        return preview

    predicted_codes = [str(seed_value + offset).zfill(width) for offset in range(len(equipments))]

    for equipment, predicted_code in zip(equipments, predicted_codes):
        current = equipment.legacy_code or ""
        if not current:
            state = STATE_SEM_CODIGO
        elif current == predicted_code:
            state = STATE_JA_PREENCHIDO
        else:
            state = STATE_CONFLITO
        preview.rows.append(
            LegacyCodeRow(
                equipment_id=equipment.pk,
                patrimonio=equipment.patrimonio,
                model_sequence=equipment.model_sequence,
                current_legacy_code=current,
                predicted_code=predicted_code,
                state=state,
            )
        )

    # Duplicidade externa: um código previsto já usado por outro
    # equipamento (de QUALQUER modelo) fora deste lote — mesmo raciocínio
    # de checagem já usado pela importação legada
    # (apps.equipment.legacy_import), aqui aplicado antes de gravar em
    # vez de depois de importar.
    equipment_ids_in_batch = [e.pk for e in equipments]
    if predicted_codes:
        clashing = (
            Equipment.objects.exclude(pk__in=equipment_ids_in_batch)
            .filter(legacy_code__in=predicted_codes)
            .values_list("legacy_code", "patrimonio")
        )
        target_by_code = {row.predicted_code: row.patrimonio for row in preview.rows}
        for code, existing_patrimonio in clashing:
            preview.external_duplicates.append(
                ExternalDuplicate(
                    code=code,
                    existing_patrimonio=existing_patrimonio,
                    target_patrimonio=target_by_code.get(code, ""),
                )
            )

    return preview


@transaction.atomic
def apply_legacy_code_bulk_fill(*, model_id: int, seed_code: str, changed_by) -> LegacyCodeBulkPreview:
    """
    Execução real. Trava a linha do `EquipmentModel` (mesmo padrão de
    `apps.equipment.services.create_equipment()`) para serializar
    confirmações concorrentes do MESMO modelo, e SÓ DEPOIS recalcula a
    prévia inteira do zero — nunca aceita a prévia como veio do
    navegador/sessão. Se a prévia recalculada estiver bloqueada por
    qualquer motivo, levanta `LegacyCodeBulkBlocked` sem gravar nada
    (a transação inteira é desfeita).

    Grava um `equipment.save(update_fields=[...])` por unidade (nunca
    `bulk_update`), com `_change_reason` antes de cada save — para
    manter o django-simple-history funcionando exatamente como em
    qualquer outra alteração de Equipment. Só grava as linhas
    SEM_CODIGO — JA_PREENCHIDO já está correto e não precisa (nem deve)
    gerar um evento de histórico artificial de "nenhuma mudança".
    """
    model = EquipmentModel.objects.select_for_update().get(pk=model_id)

    preview = build_legacy_code_bulk_preview(model_id=model.pk, seed_code=seed_code)
    if preview.blocked:
        raise LegacyCodeBulkBlocked("A prévia revalidada no servidor encontrou um bloqueio.", preview=preview)

    to_write = preview.pending_rows
    if not to_write:
        # Nada para gravar (lote inteiro já JA_PREENCHIDO) — não é erro,
        # é idempotência: devolve a prévia como está, sem tocar no banco.
        return preview

    by_id = {row.equipment_id: row for row in to_write}
    equipments = Equipment.objects.filter(pk__in=by_id.keys())
    for equipment in equipments:
        row = by_id[equipment.pk]
        equipment._change_reason = (
            f"Preenchimento em lote de código legado. Código: {row.predicted_code}. "
            f"Executado por: {changed_by}."
        )
        equipment.legacy_code = row.predicted_code
        equipment.save(update_fields=["legacy_code", "updated_at"])

    return preview
