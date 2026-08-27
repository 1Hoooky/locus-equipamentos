"""
Encerramento definitivo da limpeza dos dados de teste (unidades "TESTE",
"TESTE3", "teste2" deixadas pelos testes manuais de double-submit — ver
`apps.operations.management.commands.report_duplicate_locations`).

Histórico da decisão: a ferramenta web temporária de limpeza (tela de
diagnóstico → "Limpar duplicatas sem referências", processando em lotes
via HTTP) passou a retornar 502 Bad Gateway no Render Free mesmo depois
de reduzir o processamento por requisição — e como essa é uma limpeza
PONTUAL de dados de teste (não uma operação recorrente que precise de
UI), a decisão foi substituir a ferramenta web inteira por esta data
migration: roda uma única vez, dentro do `python manage.py migrate` do
próprio deploy, sem depender de HTTP/JavaScript/sessão/SubmissionGuard e
sem o Render Free precisar oferecer Shell. Depois desta migration, TODA a
ferramenta de escrita foi removida do código (ver
`apps.operations.views` / `apps.operations.urls` / `apps.operations.services`
— não sobrou nenhum caminho para disparar esta limpeza pelo navegador).

Escopo — deliberadamente restrito, correspondência EXATA de nome (nunca
`icontains`/fuzzy):

    TARGET_NAMES = ("TESTE", "TESTE3", "teste2")

Confirmado manualmente pelo usuário na tela de diagnóstico antes desta
migration ser escrita: esses três nomes são os únicos grupos de dados de
teste; todas as duplicatas neles SEM Movement referenciando podem ser
desativadas; a Location "TESTE" que TEM Movement referenciando (citada
como "#2 TESTE" no diagnóstico) deve ser preservada.

Regra de proteção — a ÚNICA que importa de verdade, e por isso é
verificada em TODA candidata, sem exceção: qualquer Location referenciada
por um `Movement`, como `origin_location` OU `destination_location`,
NUNCA é desativada. Isso preserva a "#2 TESTE" automaticamente, sem
precisar hardcodar nenhum pk — um pk é específico de cada banco (o pk
real em produção pode não ser 2 num ambiente de teste/CI/staging
diferente), então amarrar a proteção a um ID fixo seria frágil e não
portátil entre ambientes. A regra de integridade (tem referência → nunca
mexe) já cobre o caso com folga.

Segunda camada de proteção, redundante só por segurança: mesmo que um dos
três nomes acima algum dia colida com uma Location interna legítima
("Estoque Locus"/"Manutenção Locus", criadas pela migration
0003_seed_internal_locations), ela é explicitamente excluída do escopo.

O que esta migration NUNCA faz: hard delete; qualquer alteração em
`Movement`, `Equipment`, `Client` ou `Address`; qualquer coisa em
histórico (`django-simple-history` não é acionado por escritas feitas via
os modelos "congelados" de `apps.get_model()` dentro de uma migration —
não há registro de HistoricalLocation gerado por esta execução, e nenhum
código aqui tenta forçar isso); `.update()`/`.delete()` em massa (cada
candidata é revalidada e salva individualmente); e qualquer decisão
baseada só em "é duplicata" — o critério é nome exato + ausência de
referência, ponto.

Usa exclusivamente `apps.get_model()` (o estado histórico/congelado da
migration) para `Location` e `Movement` — nunca importa
`apps.operations.models` diretamente —, então o comportamento desta
migration não muda se os models Python atuais mudarem no futuro (ela
continua fazendo exatamente o que está escrito aqui, para sempre).

Transacional: PostgreSQL suporta DDL/RunPython transacional e o Django já
roda cada migration dentro de uma única transação por padrão nesse caso
(`Migration.atomic = True`, o default) — declarado explicitamente abaixo
por clareza. `deactivate_test_duplicate_locations()` também envolve seu
próprio corpo num `transaction.atomic()` interno, então o comportamento
"tudo ou nada" fica óbvio lendo só a função, sem precisar checar o
atributo da classe. Nenhum `time.sleep()`, nenhuma chamada HTTP, nenhuma
dependência de JavaScript/sessão/SubmissionGuard — é só leitura +
`UPDATE` de uma coluna, direto no banco, uma vez, durante o deploy.

Idempotente por construção: o filtro de entrada é `is_active=True`
combinado com o nome exato; uma Location já desativada (por esta
migration ou por qualquer outro motivo) nunca é candidata de novo — rodar
esta função mais de uma vez (ou o Django "rodar de novo" por engano) não
tem nenhum efeito adicional além da primeira execução bem-sucedida.

Reverso deliberadamente `RunPython.noop`: não existe forma segura de
distinguir, só olhando o banco, quais Locations foram desativadas
especificamente por ESTA migration versus por qualquer outra ação
administrativa que também use `is_active=False` — reativar "tudo que
está inativo e bate com esses nomes" no reverse arriscaria reativar
Locations que o usuário desativou por outro motivo depois. Se algum dia
for preciso desfazer isso, é uma decisão manual, caso a caso, feita por
um humano olhando os dados — não uma automação no reverse desta migration.
"""

from django.db import migrations, transaction

# Único allowlist de nomes elegíveis — correspondência EXATA. Ampliar
# esta lista não é uma decisão desta migration (ela já rodou uma vez no
# banco de produção e não roda de novo); é decisão humana, deliberada, em
# uma migration NOVA, se um dia houver outro incidente parecido.
TARGET_NAMES = ("TESTE", "TESTE3", "teste2")

# Redundante com o allowlist acima só por segurança — ver docstring do
# módulo.
PROTECTED_NAMES = ("Estoque Locus", "Manutenção Locus")


def deactivate_test_duplicate_locations(apps, schema_editor):
    Location = apps.get_model("operations", "Location")
    Movement = apps.get_model("operations", "Movement")

    with transaction.atomic():
        # Consulta enxuta: só os três campos usados abaixo, só Locations
        # ativas com nome exatamente num dos três grupos de teste (e não
        # numa das duas internas legítimas). Sem select_related/prefetch —
        # nada além do necessário é carregado em memória.
        candidates = (
            Location.objects.filter(is_active=True, name__in=TARGET_NAMES)
            .exclude(name__in=PROTECTED_NAMES)
            .only("id", "is_active")
            .order_by("pk")
        )

        for location in candidates:
            # A ÚNICA regra que decide preservar ou não: existe Movement
            # referenciando esta Location, como origem OU destino? Duas
            # consultas `.exists()` — nunca carrega os Movements em
            # memória, só confirma presença/ausência. Isso preserva a
            # Location "TESTE" com referência (a "#2 TESTE" do
            # diagnóstico) sem depender do valor do seu pk.
            has_reference = (
                Movement.objects.filter(origin_location_id=location.pk).exists()
                or Movement.objects.filter(destination_location_id=location.pk).exists()
            )
            if has_reference:
                continue  # Location referenciada por Movement → nunca desativar.

            location.is_active = False
            location.save(update_fields=["is_active", "updated_at"])


class Migration(migrations.Migration):
    # Default do Django para backends com DDL transacional (PostgreSQL é
    # um deles) — declarado explicitamente aqui só para deixar óbvio, sem
    # precisar saber esse default de cor: esta migration inteira roda
    # dentro de uma única transação.
    atomic = True

    dependencies = [
        ("operations", "0004_backfill_principal_locations"),
    ]

    operations = [
        migrations.RunPython(deactivate_test_duplicate_locations, migrations.RunPython.noop),
    ]
