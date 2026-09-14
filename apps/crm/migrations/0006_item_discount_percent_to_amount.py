# RODADA 3 DE REFINAMENTOS DO HUB DA OPORTUNIDADE (14/09/2026), seção
# 51-60: o desconto do ITEM (`ProposalItem`) deixa de ser PERCENTUAL
# (0-100%) e vira um valor MONETÁRIO em R$ — mesma unidade do desconto
# geral da `ProposalVersion` (`general_discount`), que já era R$.
#
# Passos, em ordem, dentro de UMA transação:
#   1. Adiciona a nova coluna `item_discount_amount` (Decimal, default
#      0.00 por enquanto — só até o passo 2 preencher os valores reais).
#   2. RunPython: para cada `ProposalItem` já existente, converte o
#      desconto percentual antigo para R$ usando a fórmula fornecida na
#      especificação: `desconto_em_reais = (quantity × unit_price) ×
#      (discount_percent / 100)`, arredondado para 2 casas decimais
#      (`ROUND_HALF_UP`, mesma convenção monetária usada em todo o
#      projeto — nunca truncamento simples).
#   3. Remove a `CheckConstraint` antiga (0-100%) e a coluna
#      `item_discount_percent`.
#   4. Adiciona as `CheckConstraint`s novas (nunca negativo; nunca maior
#      que o bruto quantidade × valor unitário).
#
# Ambiente é DEV (nunca produção — ver docs de deployment). Auditoria
# antes de escrever esta migration confirmou só 6 `ProposalItem` no
# banco no momento, apenas 1 com desconto > 0 (10%, numa versão ainda em
# RASCUNHO, nunca emitida) — o backfill do passo 2 cobre 100% das linhas
# existentes com segurança, preservando o valor comercial equivalente.

from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations, models


def backfill_discount_amount(apps, schema_editor):
    ProposalItem = apps.get_model("crm", "ProposalItem")
    cents = Decimal("0.01")
    for item in ProposalItem.objects.all().iterator():
        gross = item.unit_price * item.quantity
        discount_amount = (gross * (item.item_discount_percent / Decimal("100"))).quantize(cents, rounding=ROUND_HALF_UP)
        # Nunca deixa o backfill gerar um desconto maior que o bruto por
        # imprecisão de arredondamento (não deveria acontecer com
        # percentuais 0-100, mas a checagem é barata e evita violar a
        # CheckConstraint nova adicionada logo depois).
        if discount_amount > gross:
            discount_amount = gross
        item.item_discount_amount = discount_amount
        item.save(update_fields=["item_discount_amount"])


def reverse_backfill_discount_amount(apps, schema_editor):
    # Reverso é feito pelas operações de schema em sentido contrário
    # (RemoveField desfaz o AddField) — nada a fazer aqui além de existir
    # como par simétrico do RunPython.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0005_convert_activity_type_to_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="proposalitem",
            name="item_discount_amount",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10),
        ),
        migrations.RunPython(backfill_discount_amount, reverse_backfill_discount_amount),
        migrations.RemoveConstraint(
            model_name="proposalitem",
            name="proposal_item_discount_percent_in_range",
        ),
        migrations.RemoveField(
            model_name="proposalitem",
            name="item_discount_percent",
        ),
        migrations.AddConstraint(
            model_name="proposalitem",
            constraint=models.CheckConstraint(
                check=models.Q(("item_discount_amount__gte", 0)), name="proposal_item_discount_amount_not_negative"
            ),
        ),
        migrations.AddConstraint(
            model_name="proposalitem",
            constraint=models.CheckConstraint(
                check=models.Q(("item_discount_amount__lte", models.F("quantity") * models.F("unit_price"))),
                name="proposal_item_discount_amount_not_greater_than_gross",
            ),
        ),
    ]
