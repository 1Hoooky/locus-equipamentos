# Relatório — Fechamento da Proposta Comercial (LocusHub / CRM)

**Data:** 23/09/2026
**Escopo:** IMPLEMENTAÇÃO — FECHAMENTO DA PROPOSTA COMERCIAL / DADOS COMPLETOS + PAGAMENTOS + ENTREGA + SNAPSHOT + NOVO PDF

## 1. Resumo executivo

O objetivo desta rodada era fechar o ciclo comercial da Proposta do LocusHub para que ela saia do sistema como um documento completo, sem retrabalho manual — reaproveitando 100% o que já existia (`Proposal`/`ProposalVersion`/`ProposalItem`, versionamento, emissão, PDF, `Attachment`) e sem criar nenhum sistema paralelo de cliente, cadastro de empresa ou cálculo financeiro.

O que faltava, confirmado por auditoria prévia do código real (não da documentação): nenhuma estrutura de pagamento estruturado (só um campo de texto livre), nenhum campo de Evento/Responsável no local, nenhum helper de "valor por extenso", nenhuma ligação real entre `ProposalVersion` e o Plano Comercial (`CommercialPlan`, já existente desde a RODADA 1 mas nunca usado pela Proposta), e um PDF que não cobria integralmente o modelo de referência fornecido (`base.pdf`).

Esta rodada fechou exatamente essas lacunas. Nenhuma reconstrução do módulo de Proposta foi feita; nenhum segundo sistema de cliente/empresa foi criado; nenhum cálculo financeiro foi duplicado; emitir uma Proposta continua nunca sendo o mesmo que aceitar/vender/fechar contrato.

## 2. Auditoria inicial

Antes de qualquer código, o sistema real foi lido (models, services, forms, views, templates, migrations) para confirmar o que já existia e evitar duplicação:

- `Proposal`/`ProposalVersion`/`ProposalItem`, numeração, versionamento (auto-versionamento preguiçoso já existente desde a RODADA 4), emissão (`issue_proposal()`), cálculo financeiro (`calculate_proposal_version()`), snapshot de cliente/empresa, geração de PDF e `Attachment` — tudo confirmado funcional e reaproveitado sem alteração de comportamento.
- `CommercialPlan`/`CommercialTerm`/`PriceTableRate` (RODADA 1) — existiam, mas **nunca** tinham nenhuma ligação com `ProposalVersion` (decisão documentada como deliberadamente futura). Esta rodada criou essa ligação, só para exibição — não para cálculo de preço.
- Nenhuma estrutura de parcela/pagamento existia além do texto livre `payment_info_notes`.
- Nenhum campo de Evento/Responsável no local existia.
- Nenhum helper de "valor por extenso" existia em lugar nenhum do projeto.
- O `base.pdf` enviado pelo usuário foi lido integralmente e usado para validar o conteúdo exigido pela Seção 1 da especificação (cabeçalho, dados da Locus, dados do cliente, itens, resumo financeiro, dados de pagamento, entrega/operação, identificação das partes, local/data).

## 3. O que foi construído

### 3.1 Modelo de dados (`apps/crm/models.py`)

- **`ProposalVersionInstallment`** (novo) — parcela de pagamento por versão: `sequence`, forma de pagamento (+ complemento quando "Outro"), valor (`Decimal`), vencimento. Pertence à `ProposalVersion` (nunca à `Proposal`/`Opportunity` diretamente), clonada integralmente a cada nova versão. É um **acordo comercial de pagamento**, explicitamente **não** contas a receber/faturamento — isso continua fora de escopo (ver Seção 8).
- **`ProposalVersion`** ganhou 9 campos novos, todos aditivos: `commercial_plan` (primeira ligação real com `CommercialPlan`, só para exibição no PDF), `commercial_plan_name_snapshot`, `event_name`, `onsite_responsible_name`, `onsite_responsible_phone`, e 5 campos de snapshot ampliado (`client_type_snapshot`, `client_company_name_snapshot`, `client_trade_name_snapshot`, `company_city_snapshot`, `company_uf_snapshot`) — necessários para a apresentação PF/PJ real do cliente e para montar "Cidade - UF, DD de mês de AAAA" no rodapé sem hardcode.
- `PaymentMethod` ganhou `DINHEIRO` (enum, sem migration de dado).

### 3.2 Migração (`0014_proposalversion_client_company_name_snapshot_and_more.py`)

100% aditiva — só `AddField`, `AlterField` (choices) e `CreateModel`. Nenhum `RemoveField`, nenhum backfill/`RunPython`. Toda `ProposalVersion` já existente continua válida sem nenhum ajuste de dado.

### 3.3 Services (`apps/crm/services.py`)

- CRUD de parcela: `add_installment()` / `update_installment()` / `remove_installment()`, todas exigindo `DRAFT` primeiro (mesma imutabilidade de item/condição).
- `ensure_editable_installment()` — extensão do auto-versionamento preguiçoso já existente para parcela: editar/remover parcela de uma versão emitida clona uma nova versão DRAFT primeiro (com item, condição e todas as parcelas anteriores clonados), sem jamais escrever na versão antiga.
- `next_installment_suggestion()` — sugestão de UX (próximo número de parcela + saldo restante), nunca redistribui parcelas existentes.
- `check_payment_reconciliation()` — só leitura, alimenta o bloco "Total da proposta / Total distribuído / Diferença".
- **`validate_payment_before_issue()`** — a regra central desta rodada: chamada dentro de `issue_proposal()`, bloqueia a emissão se não houver nenhuma parcela ou se a soma não bater com o total. Nunca bloqueia o rascunho.
- `create_new_version()` passou a clonar também as parcelas, na mesma transação.
- `apps/crm/extenso.py` (novo módulo) — `valor_por_extenso(Decimal) -> str`, casca fina sobre `num2words` (pt-BR), sempre derivado, nunca `float`, nunca armazenado.
- `apps/crm/pdf.py` ganhou os cálculos auxiliares (totais por tipo de item, texto por extenso, data por extenso) — `calculate_proposal_version()` continua a única autoridade sobre subtotal/total.

### 3.4 Forms e Views

- `ProposalConditionsForm` ganhou os 4 campos novos de condição (plano, evento, responsável, telefone).
- `ProposalInstallmentForm` (novo), sempre com `prefix="parcela"` para não colidir com os campos de `ProposalConditionsForm` na mesma página.
- 3 views novas (`ProposalInstallmentAddView`/`UpdateView`/`RemoveView`), mesmo padrão e mesma permissão (`crm.change_opportunities`) das views de item já existentes — POST-only, com CSRF, IDOR protegido do mesmo jeito.

### 3.5 PDF (`templates/crm/pdf/proposal.html`)

Reescrito por completo seguindo a hierarquia pedida: cabeçalho → dados da Locus → dados do cliente (PF/PJ) → condições comerciais → produtos e serviços → resumo financeiro (com valor por extenso) → condições de pagamento (tabela de parcelas) → entrega/operação (omitido em Venda) → informações complementares → identificação das partes → local e data. CSS multipage-safe — nunca corta uma linha de tabela no meio.

### 3.6 UI (`templates/crm/_proposal_composition.html`)

Novo bloco "Condições de pagamento" entre Resumo financeiro e Informações complementares: tabela de parcelas, reconciliação (Total da proposta / Total distribuído / Diferença + badge), painel "+Adicionar parcela" com sugestão de saldo. Campos de Plano/Evento/Responsável adicionados aos blocos já existentes, mesmos tokens visuais.

## 4. Testes

- **Baseline real, medido antes de qualquer alteração** (Seção 56): `pytest apps/crm -q` → **506 passed**.
- **1 arquivo de teste novo**, `test_proposal_closure_payment_snapshot_pdf.py` — **59 testes** cobrindo CRUD de parcela, reconciliação, validação na emissão, versionamento de pagamento, fluxo HTTP real, imutabilidade do snapshot (alterar cliente/empresa/vendedor/plano depois da emissão não muda o documento), valor por extenso (7 valores, incluindo `TypeError`/`ValueError`), conteúdo do PDF via extração real (`pdfplumber`), exibição PF/PJ, Venda vs. Locação, composição mista equipamento+serviço, e confirmação de que nenhuma `Permission` nova foi criada.
- **7 arquivos de teste legados ajustados** (não por bug — porque a nova validação obrigatória de pagamento na emissão passou a exigir pelo menos 1 parcela configurada, e esses testes foram escritos antes desta rodada): todos passaram a configurar 1 parcela cobrindo o total antes de emitir, via um helper compartilhado (`_payment_test_helpers.py::add_full_installment()`), sem enfraquecer nenhuma asserção original.
- **Resultado final**: `pytest apps/crm -q` → **565 passed** (506 + 59, zero regressão).
- `manage.py check`: limpo. `makemigrations --check --dry-run`: "No changes detected".
- Suíte completa do projeto (excluindo 5 módulos com erro de coleção pré-existente, já documentado e confirmado via `git stash -u` como anterior a esta implementação): **1551 passed, 9 failed** — os 9 confirmados pré-existentes na árvore limpa, nenhum em `apps/crm`.

## 5. Validação em navegador real (Playwright)

Sessão real com `runserver` (dev DB local, dados de teste removidos ao final) cobrindo o fluxo ponta a ponta:

1. Abrir Oportunidade → aba "Produtos e Serviços" → adicionar item (2× Aquecedor Smoke, R$1.530,00 cada = **R$3.060,00**, o mesmo valor do exemplo de referência da especificação).
2. Salvar condições: Plano Comercial, Evento ("Expoingá 2027"), Responsável no local ("João da Silva") e telefone, período contratado.
3. Adicionar 1ª parcela (R$1.000,00, PIX) → UI mostra "Diferença" corretamente, **sem** "Pagamento conferido".
4. Tentar emitir com pagamento divergente → **bloqueado**, versão permanece "Rascunho".
5. Adicionar 2ª parcela (R$2.060,00, Boleto) → soma bate → "Pagamento conferido".
6. Emitir → PDF baixado automaticamente, versão passa a "Emitida".
7. **Conteúdo do PDF confirmado por extração de texto** — todos os campos-chave presentes e corretos: "PROPOSTA-000004", "LOCAÇÃO COMUM", dados da Locus, cliente PJ (razão social + nome fantasia + CNPJ), item com período, "Total da Proposta R$ 3.060,00", **"Valor por extenso: três mil e sessenta reais"**, tabela de parcelas (PIX R$1.000,00 / Boleto R$2.060,00), bloco ENTREGA/OPERAÇÃO com Evento/Responsável/telefone/local, "PROPONENTE"/"CLIENTE", e **"Maringá - PR, 23 de setembro de 2026"** — exatamente o formato pedido pela especificação.
8. Adicionar uma 3ª parcela **depois** da emissão → auto-versionamento disparado automaticamente: nova versão "— Versão 2" (Rascunho) criada, com as 2 parcelas anteriores clonadas + a nova; a versão 1 (Emitida) permanece intocada — confirmado tanto pela UI quanto consultando o banco diretamente (a versão 1 continua com total R$3.060,00 e só as 2 parcelas originais; o PDF já baixado da versão 1 continua mostrando só essas 2 parcelas, mesmo com a versão 2 já tendo 3).

**Limitação da validação visual**: este ambiente de sandbox bloqueia o CDN do Tailwind (`cdn.tailwindcss.com`) do qual o projeto já depende hoje para estilização em tempo de execução (característica pré-existente do projeto, não introduzida por esta rodada — documentada no próprio template `_design_tokens.html` como pendência de build step). Por isso as capturas de tela desta sessão mostram HTML funcionalmente correto mas sem o CSS aplicado. A verificação de CSS/Light-Dark não foi refeita visualmente por esse motivo; como já registrado em rodadas anteriores da documentação do projeto, **não existe dark mode sitewide no LocusHub** — os novos campos usam exatamente os mesmos tokens/classes já existentes, sem CSS novo, então não há nada de novo para "quebrar" num tema escuro que não existe.

## 6. Documentação

Atualizados (convenção do projeto: subseções datadas, nunca reescrita in-place): `docs/apps/crm.md` (Models/Services/Forms/Views/URLs/Templates/Migrations/Testes/Pontos importantes), `docs/flows.md` (novo fluxo 11-A de parcelas + validação na emissão; correção da referência obsoleta ao `ProposalNewVersionView`, removido desde a RODADA 4), `docs/permissions.md` (confirmação de que nenhuma `Permission` nova foi criada).

## 7. Fora de escopo (confirmado, não implementado)

Contas a receber, baixa de boleto, integração bancária, geração de PIX, cobrança automática, conciliação financeira, NF, assinatura eletrônica, agendamento, movimentação física de equipamento a partir do pagamento, recorrência financeira, reajuste/renovação contratual, Contrato completo, combos Bares e Restaurantes.

## 8. Limitações conhecidas (disclosed)

- `ProposalInstallmentUpdateView` existe e tem cobertura de teste completa, mas a UI atual só oferece "+Adicionar parcela" e "Remover" — não há edição inline de uma parcela já configurada (mesma limitação já documentada para item de proposta: remover e adicionar de novo).
- A ligação `ProposalVersion.commercial_plan` é só para exibição — a composição da proposta ainda não usa `CommercialTerm`/`PriceTableRate` para sugerir preço por plano+prazo (permanece registrado como próxima rodada futura, já era assim antes desta implementação).
- Validação visual de CSS limitada nesta sessão pelo bloqueio de rede ao CDN do Tailwind (ver Seção 5) — recomenda-se uma conferência visual rápida em ambiente com acesso à internet antes de considerar a rodada 100% fechada visualmente (a lógica/conteúdo já está 100% validada).

## 9. Estado do repositório

- Commit local criado (`5fceb8b`, branch `master`) na cópia deste ambiente — **não enviado (push) a nenhum remoto**, conforme a restrição já combinada.
- Os 23 arquivos alterados/criados foram também escritos diretamente na pasta do projeto no computador do usuário (`OneDrive\Desktop\locus-equipamentos`), **sem nenhuma operação de git** feita ali (nem `add`, nem `commit`) — a pasta tem um histórico de commits próprio, feito por outra pessoa (`1Hoooky`) em paralelo a este trabalho, incluindo commits de hoje; por segurança, nenhuma tentativa de sincronizar/mesclar histórico de git foi feita automaticamente. Os arquivos estão lá como alterações não commitadas, prontos para revisão e commit pelo time no Windows.
- Nenhuma alteração em PROD/Oracle. Nenhuma migração rodada em produção. Nenhum push feito.

## 10. Baseline — antes × depois

| Métrica | Antes | Depois |
|---|---|---|
| `pytest apps/crm -q` | 506 passed | 565 passed (+59, 0 regressão) |
| `manage.py check` | limpo | limpo |
| `makemigrations --check --dry-run` | limpo | limpo ("No changes detected") |
| Suíte completa do projeto | 1492 passed / 4 failed pré-existentes (RODADA 1) | 1551 passed / 9 failed — todos confirmados pré-existentes via `git stash -u` |
