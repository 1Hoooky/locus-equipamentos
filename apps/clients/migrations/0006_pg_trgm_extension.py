# Migração escrita à mão (não gerada por `makemigrations`) — CORRIGIR
# DEFINITIVAMENTE O CAMPO CLIENTE / AUTOCOMPLETE PESQUISÁVEL (12/09/2026).
#
# Ativa a extensão `pg_trgm` (nativa do Postgres, contrib padrão — "text
# similarity measurement and index searching based on trigrams") usada
# pelo terceiro nível de relevância da busca de clientes do novo
# autocomplete (`apps.crm.views.OpportunityClientAutocompleteView`):
# 1º prefixo exato, 2º contém, 3º similaridade aproximada real via
# `TrigramSimilarity`, para nomes digitados com pequena diferença
# (erro de digitação, abreviação) não ficarem de fora nem virarem
# resultado aleatório.
#
# NENHUMA mudança de campo/model/tabela — só ativa um recurso do
# próprio banco (`CREATE EXTENSION IF NOT EXISTS pg_trgm`), então não
# aparece em `makemigrations --check --dry-run` (que só detecta
# mudanças de schema derivadas dos models) e não adiciona nenhuma
# coluna nova em `Client`. Decisão confirmada explicitamente com o
# usuário antes de ser aplicada (a extensão já estava disponível neste
# Postgres, só não instalada).
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0005_seed_cargo_architecture_base"),
    ]

    operations = [
        TrigramExtension(),
    ]
