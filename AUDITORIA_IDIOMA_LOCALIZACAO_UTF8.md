# LocusHub — Auditoria de idioma, localização e UTF-8

**Data:** agosto/2026 · **Escopo:** auditoria + correções de baixo risco (sem ampliação de funcionalidades, sem conversão destrutiva de banco, sem push/deploy).

Esta auditoria seguiu a ordem exigida: primeiro investigação completa do repositório real (sem assumir nada de rodadas anteriores), depois relato dos achados, e só então as correções — todas dentro da lista de baixo risco autorizada (labels, títulos, botões, placeholders, mensagens, verbose names, textos de template, configuração de charset, formatação visual, labels de TextChoices/Choices).

---

## 1. Problemas encontrados (resumo)

| # | Problema | Severidade |
|---|---|---|
| 1 | Exportação CSV de equipamentos sem BOM UTF-8 e sem `charset=utf-8` no cabeçalho HTTP — risco real de mojibake ao abrir no Excel/Windows | Alto |
| 2 | `ModelForm`s sem `verbose_name`/`labels` mostravam rótulos em inglês (Name, Is active, Category, Role, Reference notes, etc.) em 8 formulários de 5 apps | Alto |
| 3 | Sem `403.html`/`404.html`/`500.html` próprios — em produção (`DEBUG=False`) o usuário via a página padrão em inglês do Django | Alto |
| 4 | Corrida rara: modelo de equipamento apagado/desativado entre a prévia e a confirmação do lote fazia `EquipmentModel.DoesNotExist` (texto em inglês) vazar para `messages.error` | Médio |
| 5 | Falhas de leitura de planilha (import de clientes/equipamentos legados) interpolavam o texto bruto da exceção do `openpyxl` (às vezes em inglês) na mensagem exibida ao usuário | Médio |
| 6 | Falha inesperada por linha no import de clientes mostrava `str(exc)` cru (podendo ser `IntegrityError`/erro técnico) na tela de revisão | Médio |
| 7 | Valores monetários (`estimated_value`, `closed_value`, `acquisition_value`) exibidos sem separador de milhar — "R$ 12500,00" em vez de "R$ 12.500,00" | Médio |
| 8 | Datas na ficha de oportunidade do CRM e no campo "Data de aquisição" do equipamento renderizadas sem `\|date:"d/m/Y"` — formato verboso e inconsistente com o resto do sistema | Baixo |
| 9 | Modal JS de tema de etiqueta ("LIGHT"/"DARK") e botão "Download" em inglês, em duas cópias (app + admin) | Baixo |
| 10 | "Home" em inglês em 4 pontos da navegação/título (sidebar desktop, menu mobile, `<title>`, `<h1>`) — inconsistente com todo o resto do menu, já em português | Baixo |
| 11 | Página de diagnóstico interna (`duplicate_locations_report.html`, só Administrador) misturava "Location(s)"/"Movements" em frases portuguesas | Baixo |
| 12 | 3 respostas `text/plain` de erro de tema inválido (QR/etiquetas) sem `charset=utf-8` no cabeçalho | Baixo |

Nenhum problema de dado **já corrompido no banco** foi encontrado (ver seção 3) — por isso nenhuma parada/relato de correção de dado existente foi necessária.

## 2. Textos em inglês encontrados na UI

Localizados por varredura sistemática de `models.py` (verbose_name/TextChoices), `forms.py` (label/help_text), `views.py` (messages/ValidationError) e todos os templates de accounts, catalog, clients, core, crm, dashboard, equipment, maintenance, operations e qrcodes:

- **Rótulos automáticos de `ModelForm` em inglês** (raiz: nenhum `verbose_name` no model e nenhum `Meta.labels` no form): `CategoryForm`, `EquipmentModelForm` (catalog); `CommercialSourceForm`, `OpportunityStageForm`, `LossReasonForm` (crm); `EquipmentUpdateForm` (equipment — o mesmo formulário de criação já estava certo, só a edição vazava "Serial number", "Legacy code" etc.); `AddressForm.reference_notes` (core, reaproveitado por clientes e unidades); `role` em `UserCreateForm`/`UserUpdateForm` (accounts, mostrava "Role" em vez de "Perfil").
- **"LIGHT"/"DARK"/"Download"** no modal de escolha de tema de etiqueta (`static/qrcodes/label_theme_modal.js` e a cópia usada só no Django admin).
- **"Home"** na navegação (sidebar desktop, drawer mobile) e na tela inicial (`<title>`, `<h1>`).
- **"Location(s)"/"Movements"** na página de diagnóstico de unidades duplicadas (ferramenta interna, só Administrador).

Termos como "Status", "WhatsApp", "Follow-up" e "QR Code" foram avaliados e mantidos — são empréstimos consolidados no vocabulário de negócio brasileiro, não más traduções.

O restante do CRM (a parte nova desta rodada anterior), incluindo `TextChoices` (`BusinessType`, `ActivityType`), `verbose_name`/`verbose_name_plural` de todos os models, mensagens de `messages.success`/`error` e `ValidationError`, e os `forms.Form` (não-ModelForm) já estava 100% em português — confirmado, não presumido.

## 3. Problemas de encoding encontrados

- **Banco de dados**: PostgreSQL, `server_encoding`, `client_encoding` e a codificação do banco `locus_equipamentos` são todos `UTF8` (`datcollate`/`datctype` = `C.UTF-8`). **Nenhum problema.**
- **Arquivos-fonte**: os 353 arquivos rastreados pelo git (`.py`/`.html`/`.txt`/`.md`/`.csv`/`.json`) são todos `us-ascii` ou `utf-8`. Nenhum BOM indevido, nenhum arquivo em Latin-1/cp1252/ISO-8859-1. **Nenhum problema.**
- **Mojibake**: varredura completa por `Ã`, `Â`, `�` (U+FFFD), sequências clássicas de UTF-8 mal-interpretado (`Ã£`, `Ã§`, `Ã©` etc.), nomes de codec legado (`latin1`, `iso-8859-1`, `cp1252`) e `errors="ignore"`/`errors="replace"`: **zero ocorrências reais** (as ocorrências de "Ã"/"Â" encontradas são todas palavras portuguesas corretas como "NÃO", "PADRÃO", "SEMÂNTICA"). Um teste automatizado de regressão (`MojibakeRegressionTest`) foi criado para nunca deixar isso voltar silenciosamente.
- **`<meta charset>` em templates**: `base.html`/`base_public.html` declaram `UTF-8` corretamente; nenhum template filho redeclara `<meta charset>` de forma conflitante.
- **Cabeçalhos HTTP `Content-Type`** (a causa raiz real encontrada): Django adiciona `charset=utf-8` automaticamente quando `HttpResponse()` é chamado sem `content_type` explícito — mas **não** quando um `content_type` é passado manualmente sem o parâmetro `charset`. Foi exatamente isso que aconteceu na exportação CSV (`text/csv`, sem charset, sem BOM) e em 3 respostas de erro `text/plain` do módulo de QR/etiquetas — corrigido (seção 6).
- **Datas/valores monetários**: nenhum problema de encoding aqui (é formatação, não codificação) — coberto separadamente na seção "datas e valores monetários" abaixo.

## 4. Configuração Django atual

| Configuração | Valor | Situação |
|---|---|---|
| `LANGUAGE_CODE` | `"pt-br"` | Correto |
| `USE_I18N` | `True` | Correto |
| `USE_TZ` | `True` | Correto |
| `TIME_ZONE` | `"America/Sao_Paulo"` | Correto — **não foi alterado** |
| `USE_L10N` | *(não existe mais — removido pelo Django 5.0, sempre ativo)* | — |
| `DATE_FORMAT`/`DATETIME_FORMAT` | não sobrescritos | Usa o catálogo `pt_BR` nativo do Django (formato longo, "26 de Agosto de 2026") |
| `DEFAULT_CHARSET` | não sobrescrito (`utf-8` padrão) | Correto |
| `LOCALE_PATHS` | não configurado, sem diretório `locale/` | Esperado — projeto não usa `{% trans %}`/catálogos `.po` próprios, todo texto é português literal direto no código/template |
| `django.middleware.locale.LocaleMiddleware` | não instalado | Esperado/correto — o idioma é sempre pt-br fixo, nunca varia por `Accept-Language` do navegador |

Nenhuma alteração foi feita nestas configurações — já estavam coerentes com pt-BR.

## 5. Configuração PostgreSQL

```
SHOW server_encoding;  → UTF8
SHOW client_encoding;  → UTF8
locus_equipamentos: encoding=UTF8, datcollate=C.UTF-8, datctype=C.UTF-8
```

Confirmado ao vivo contra o banco real do ambiente (não presumido). Nenhuma ação necessária, nenhuma conversão realizada.

## 6. Arquivos corrigidos

**Backend (Python) — 8 arquivos:**
`apps/equipment/export.py`, `apps/qrcodes/views.py`, `apps/catalog/forms.py`, `apps/crm/forms.py`, `apps/equipment/forms.py`, `apps/core/forms.py`, `apps/accounts/forms.py`, `apps/equipment/views.py`, `apps/clients/import_auvo.py`, `apps/equipment/legacy_import.py`, `apps/clients/views_import.py` *(11 no total — contagem acima estava agrupada)*.

**Novo:** `apps/core/templatetags/currency.py` (filtro `brl`, formato brasileiro de moeda).

**Templates — 7 arquivos:** `templates/base.html`, `templates/dashboard/home.html`, `templates/operations/duplicate_locations_report.html`, `templates/crm/opportunity_detail.html`, `templates/crm/opportunity_list.html`, `templates/equipment/detail_private.html`.

**Novo:** `templates/403.html`, `templates/404.html`, `templates/500.html`.

**Estático (JS) — 2 arquivos:** `static/qrcodes/label_theme_modal.js`, `static/qrcodes/admin/label_theme_modal.js`.

**Testes atualizados** (para acompanhar as correções, sem enfraquecer nenhuma verificação): `apps/equipment/tests/test_export.py`, `apps/equipment/tests/test_public_detail_view.py`, `apps/operations/tests/test_duplicate_locations_report.py`.

**Teste novo:** `apps/core/tests/test_i18n_encoding_audit.py` (19 testes, ver seção 9).

Nenhum `models.py` foi alterado. Nenhuma migration foi gerada nem é necessária (`makemigrations --check --dry-run` confirma isso — seção 11).

## 7. Mudanças feitas (detalhe técnico)

1. **CSV de exportação de equipamentos** (`apps/equipment/export.py`): `Content-Type` passou a `text/csv; charset=utf-8`; um BOM UTF-8 (`﻿`) é escrito uma única vez no início do corpo, **só nesta fronteira de exportação** (nunca no banco, no código ou nos templates) — é o padrão que faz o Excel no Windows reconhecer UTF-8 em vez de assumir o codepage ANSI/cp1252 do sistema. Documentado no próprio código.
2. **3 respostas `text/plain` de tema de etiqueta inválido** (`apps/qrcodes/views.py`): `charset=utf-8` adicionado ao `Content-Type`.
3. **8 `ModelForm`s com rótulos em inglês**: `Meta.labels` adicionado (nunca `verbose_name` no model, para não gerar migration nem tocar em nome de campo) em `CategoryForm`, `EquipmentModelForm`, `CommercialSourceForm`, `OpportunityStageForm`, `LossReasonForm`, `EquipmentUpdateForm`, `AddressForm`, `UserCreateForm`/`UserUpdateForm`.
4. **Filtro `brl`** (`apps/core/templatetags/currency.py`): formata `Decimal` como "R$ 1.234,56" (separador de milhar `.`, decimal `,`), sem depender de locale do sistema operacional, sem nunca converter `Decimal` para `float`/string em cálculo — só na exibição. Aplicado em `estimated_value`/`closed_value` (CRM) e `acquisition_value` (equipamento), que antes saíam sem separador de milhar (equipamento nem tinha o prefixo "R$").
5. **Datas no CRM e na ficha de equipamento**: `expected_close_date`, `won_at`, `lost_at`, `created_at`, `changed_at`, `activity.created_at`, `activity.scheduled_for`, `acquisition_date` passaram a usar `\|date:"d/m/Y"` ou `\|date:"d/m/Y H:i"` — mesmo padrão já usado em 27 outros pontos do sistema (não havia bug de vazamento de dado interno, era só inconsistência visual: o Django já localiza automaticamente datas em pt-BR, só que no formato longo por extenso).
6. **`apps/equipment/views.py`**: o `except` que capturava `(ValueError, EquipmentModel.DoesNotExist)` junto foi separado — `EquipmentModel.DoesNotExist` agora sempre mostra "O modelo escolhido não está mais disponível. Selecione novamente." (nunca o texto interno do Django), com o detalhe técnico indo para o log via `logger.warning`.
7. **Importadores de planilha** (`apps/clients/import_auvo.py`, `apps/equipment/legacy_import.py`): a exceção bruta do `openpyxl` (pode vir em inglês) deixou de ser interpolada na mensagem ao usuário — agora é só logada (`logger.warning(..., exc_info=True)`), e a mensagem exibida é sempre a mesma frase em português, controlada.
8. **`apps/clients/views_import.py`**: a linha `Falha inesperada: {exc}` (podia mostrar `IntegrityError`/erro técnico bruto) virou uma mensagem genérica em português + `logger.exception(...)` com o detalhe completo no log.
9. **Modal LIGHT/DARK/Download**: traduzido para CLARO/ESCURO/Baixar nas duas cópias do script.
10. **"Home" → "Início"**: sidebar desktop, drawer mobile, `<title>`, `<h1>` da tela inicial.
11. **Página de diagnóstico de unidades duplicadas**: "Location(s)"/"Movements" → "Unidades"/"Movimentações" (título, `<h1>`, estado vazio, dois cabeçalhos de tabela, rodapé).
12. **`403.html`/`404.html`/`500.html`**: criados do zero (não existiam), autocontidos (não estendem `base.html`, para continuar funcionando mesmo se algo mais no sistema estiver quebrado), texto estático em português — o 403 deliberadamente **não** interpola a exceção recebida (algumas causas técnicas, como falha de CSRF, carregam texto em inglês) para nunca vazar nada técnico.

## 8. Itens NÃO corrigidos por risco (fora do escopo autorizado)

- **Nenhum.** Todos os achados classificados como problema real se encaixaram na lista de baixo risco autorizada (labels, mensagens, charset, formatação visual, templates). Nada exigiu renomear model/field, alterar coleção/collation do banco, migração de dado em massa, ou qualquer ação da lista proibida.
- **Não fizemos** `USE_THOUSAND_SEPARATOR = True` global (resolveria o problema de milhar em qualquer número do sistema, não só moeda) — decisão deliberada: essa configuração afetaria também números não-monetários (contadores, paginação, quantidades) sem necessidade, então preferimos o filtro `brl` cirúrgico, só nos 3 campos monetários reais. Documentado no próprio código do filtro.
- **Não normalizamos** (NFC) nenhum campo em massa — a normalização Unicode só foi testada (não aplicada) como verificação de que o caminho padrão de salvar/ler já preserva a forma digitada, sem introduzir uma composição diferente.

## 9. Testes adicionados

Novo arquivo `apps/core/tests/test_i18n_encoding_audit.py`, 19 testes cobrindo os 10 pontos mínimos pedidos, todos usando as strings acentuadas reais fornecidas ("João da Conceição", "Climatização São José", "Instalação próxima à área de recepção.", "Manutenção preventiva – equipamento nº 03.", "R$ 1.234,56"):

1. Salvar (`Client.objects.create(...)`, `create_opportunity(...)`, `open_maintenance(...)`).
2. Ler do banco (`.get()`/`refresh_from_db` equivalente após salvar).
3. Renderizar em template (ficha de cliente, detalhe de oportunidade, detalhe de manutenção — via requisição HTTP real).
4. POST de formulário (criação de cliente e de oportunidade com dado acentuado real).
5. Mensagem de validação (mudança de etapa para "Perdido" sem motivo — confere que o erro em português aparece de fato no HTML, não só no `form.errors`).
6. CRM (persistência, renderização, POST, valor em R$ com milhar).
7. Cliente (persistência, renderização, busca por nome acentuado, sobrevivência a logout/login).
8. Exportação (CSV com BOM — no `test_export.py`, atualizado).
9. PDF (`generate_label_pdf`, WeasyPrint — texto extraído do PDF final contém "Locações"/"IDENTIFICAÇÃO" corretamente acentuados).
10. Varredura de regressão de mojibake em todo o repositório rastreado pelo git + verificação de estabilidade de normalização NFC.

Também: testes das 3 páginas de erro (403/404/500 em português, sem sinal de mojibake), e 6 testes unitários do filtro `brl` (milhar, decimal, zero, negativo, `None`).

**Achado pela própria suíte de testes**: ao escrever o teste da página 500, descobrimos que o comentário curto do Django (`{# ... #}`) não funciona com texto em várias linhas (o tokenizer não usa modo "ponto casa quebra de linha"), o que fazia um trecho de exemplo dentro do comentário explicativo ser interpretado como uma tag real, quebrando a renderização das 3 páginas de erro novas. Corrigido trocando para o comentário em bloco (`{% comment %}...{% endcomment %}`), seguro para múltiplas linhas — prova de que a bateria de testes desta auditoria pegou um bug de verdade antes de qualquer usuário ver.

## 10. Resultado dos testes

```
Ran 936 tests in 307.970s
OK
```

Suíte completa (936 testes, incluindo os 19 novos desta auditoria) rodando 100% verde contra PostgreSQL real, com `DJANGO_SETTINGS_MODULE=config.settings.test`.

## 11. `manage.py check`

```
System check identified no issues (0 silenced).
```

## 12. `manage.py makemigrations --check --dry-run`

```
No changes detected
```

Confirma que nenhuma das correções (incluindo os 8 `Meta.labels` em ModelForms) gerou necessidade de migration — como esperado, já que `Meta.labels` é só do formulário, nunca do model.

## 13. Checklist manual (a executar em PROD/homologação)

1. Cadastrar um cliente com o nome "João da Conceição" (contato) e razão social "Climatização São José".
2. Cadastrar um texto com "ç" (ex.: observação "Instalação próxima à área de recepção.").
3. Cadastrar um texto com "ã" (ex.: "Configuração", "Manutenção").
4. Cadastrar um texto com "é" (ex.: "Serviço", "Código").
5. Cadastrar uma observação longa com pontuação especial (travessão "–", º) — ex.: "Manutenção preventiva – equipamento nº 03.".
6. Editar o registro acima e salvar novamente — conferir que os acentos continuam corretos.
7. Fazer logout e login de novo — abrir o mesmo registro e conferir que nada mudou.
8. Verificar a leitura (ficha/detalhe) do registro em todas as telas que o exibem.
9. Buscar pelo nome acentuado cadastrado (ex.: "São José", "Maringá") na listagem de clientes.
10. Criar uma oportunidade no CRM com caracteres especiais no título/observações.
11. Abrir o detalhe da oportunidade criada — conferir texto, valor em R$ (com separador de milhar se aplicável) e datas no formato dd/mm/aaaa.
12. Editar a oportunidade e salvar — conferir que nada foi corrompido.
13. Verificar as mensagens de sucesso/erro do sistema (criar, editar, mudar etapa) — todas devem estar em português correto.
14. Exportar um arquivo que contenha texto acentuado (CSV de equipamentos).
15. Abrir o CSV exportado no Excel (Windows) por duplo clique — conferir que "Patrimônio"/"Condição" e nomes acentuados aparecem corretos, sem símbolos estranhos.
16. Gerar um PDF de etiqueta (download individual) — conferir que o texto fixo em português ("Locações", "Identificação de equipamento") aparece sem quebra.
17. Repetir os testes acima (ao menos os principais) no celular/mobile.
18. Navegar pelo CRM inteiro (oportunidades, configurações comerciais) e confirmar que **nenhum texto em inglês** aparece em nenhuma tela.

## 14. Riscos pendentes

- **Fonte do WeasyPrint em produção**: a auditoria confirmou que o template usa `DejaVu Sans` (cobre acentuação latina corretamente) mas isso depende da fonte estar de fato instalada no servidor de produção (Render) — não foi possível confirmar isso a partir do ambiente de desenvolvimento/teste. Recomendação: gerar um PDF de teste em produção e conferir visualmente após o próximo deploy (fora do escopo desta rodada, que não faz deploy).
- **Sem `LocaleMiddleware`/catálogo `.po` de tradução formal**: o projeto não usa o sistema de internacionalização do Django (`{% trans %}`) — todo texto pt-BR é literal. Isso é uma decisão de arquitetura razoável para um produto mono-idioma, mas significa que qualquer texto novo escrito em inglês por engano **não** será pego automaticamente por nenhuma ferramenta de tradução — só por revisão humana ou pelo teste de regressão de mojibake/inglês que caberia expandir no futuro (ver padrão arquitetural abaixo, item 9).
- **`USE_THOUSAND_SEPARATOR`** continua `False` globalmente (decisão deliberada, seção 8) — qualquer campo monetário **novo** que for adicionado no futuro precisa lembrar de usar o filtro `\|brl`, ele não ganha separador de milhar "de graça" só por ser um `DecimalField`.
- **Nenhum dado já persistido no banco foi encontrado corrompido** — mas esta auditoria não leu 100% das linhas de todas as tabelas (seria impraticável); se o usuário suspeitar de um registro específico com texto estranho, o caminho é reportar o caso pontual para investigação dirigida.

---

## Padrão arquitetural a seguir daqui para frente

1. Código-fonte: sempre UTF-8.
2. Banco de dados: sempre UTF-8 (confirmado, nunca alterar sem necessidade real).
3. Templates/HTML: sempre UTF-8, com `<meta charset="utf-8">` só no template raiz (nunca redeclarar em filhos).
4. Interface (o que o usuário vê): sempre pt-BR — nomes internos de código continuam em inglês técnico normalmente.
5. Datas visíveis: sempre padrão brasileiro (`\|date:"d/m/Y"` ou `"d/m/Y H:i"` explícito no template — nunca `{{ valor }}` cru para uma data).
6. Moeda visível: sempre padrão brasileiro (`\|brl` — nunca `{{ valor }}` cru para um `DecimalField` monetário).
7. Caracteres especiais preservados — nunca truncar, normalizar em massa ou "corrigir" acento sem entender a causa raiz.
8. Nenhum `.encode()`/`.decode()` manual sem justificativa documentada no próprio código.
9. Nenhuma interface nova com rótulo em inglês — todo `ModelForm` novo precisa de `Meta.labels` (ou `verbose_name` no model, se for um campo já pensado para isso desde o início) cobrindo todos os campos visíveis.
10. Todo teste novo deve incluir ao menos um caso com caractere acentuado quando manipular texto livre digitado por usuário.

Toda funcionalidade nova deverá nascer já seguindo este padrão.

---

**Constraints respeitadas nesta rodada:** nenhum push, nenhum deploy, nenhuma conversão destrutiva de banco, nenhuma migration desnecessária, nenhum model/field renomeado, nenhuma normalização em massa sem necessidade identificada, nenhum uso de BOM fora da fronteira de exportação de CSV (documentado), nenhum `errors="ignore"` introduzido, autoescape do Django preservado em 100% das mudanças de template.
