# Checklist de homologação — Fechamento da Proposta Comercial (23/09/2026)

Checklist manual para o time comercial/produto validar em ambiente de homologação antes de considerar a rodada encerrada. Todos os itens abaixo já foram exercitados automaticamente (565 testes em `apps/crm`) e/ou validados numa sessão real de navegador (Playwright, dev server) durante o desenvolvimento — este checklist serve para a validação humana final.

## 1. Cabeçalho e identificação

- [ ] Número da proposta aparece como "PROPOSTA-000123" (nunca o ID técnico do banco).
- [ ] Data de emissão no formato dd/mm/aaaa.
- [ ] Nome do Plano Comercial (ex.: "LOCAÇÃO MENSAL") aparece no cabeçalho quando configurado.
- [ ] Sem plano configurado, o cabeçalho mostra só "Proposta Comercial", sem erro/campo em branco estranho.

## 2. Dados da Locus

- [ ] Razão social, CNPJ, endereço, telefone e e-mail vêm de "Dados da empresa" (`CompanyProfile`), sem nenhum texto hardcoded.
- [ ] Vendedor exibido é o responsável (owner) real da Oportunidade.

## 3. Dados do cliente

- [ ] Cliente Pessoa Jurídica: mostra Razão social + Nome fantasia + CNPJ (CPF em branco/ausente).
- [ ] Cliente Pessoa Física: mostra Nome + CPF (Razão social/Nome fantasia/CNPJ ausentes).
- [ ] Endereço, telefone e e-mail do cliente conferem com o cadastro no momento da emissão.

## 4. Produtos e serviços

- [ ] Tabela mostra Descrição / Período / Valor unitário / Quantidade / Valor total.
- [ ] Nenhuma linha mostra número de patrimônio/série — sempre modelo + quantidade.
- [ ] Itens de Serviço (ex. "Hora técnica") aparecem lado a lado com itens de Equipamento, mesma formatação.
- [ ] Período por item usa o período contratado da versão; em Venda, mostra "—".

## 5. Resumo financeiro

- [ ] Total em equipamentos, desconto, juros e frete somam corretamente para o Total da Proposta.
- [ ] Nomenclatura é "RESUMO FINANCEIRO" / "TOTAL DA PROPOSTA" — nunca "DADOS DO CONTRATO"/"VALOR DO CONTRATO".
- [ ] "Valor por extenso" aparece logo abaixo do total e bate com o valor numérico (ex.: R$ 3.060,00 → "três mil e sessenta reais").

## 6. Condições de pagamento

- [ ] Painel "+Adicionar parcela" cria uma nova parcela com forma de pagamento, valor e vencimento.
- [ ] "Total da proposta", "Total distribuído" e "Diferença" batem com o que foi configurado.
- [ ] Com soma divergente, aparece claramente o estado de divergência e a emissão fica bloqueada.
- [ ] Ajustar as parcelas até a soma bater faz aparecer "Pagamento conferido".
- [ ] Alterar o total (ex. mudar desconto) depois de já ter parcela configurada volta a mostrar divergência — nenhuma parcela é alterada sozinha.
- [ ] PDF mostra a tabela "DADOS DO PAGAMENTO" com Parcela / Forma / Valor / Vencimento, uma linha por parcela.
- [ ] "Outro" como forma de pagamento pede a descrição complementar.

## 7. Entrega / operação

- [ ] Campos "Evento", "Responsável no local" e "Telefone do responsável" salvam e aparecem no PDF.
- [ ] Bloco ENTREGA/OPERAÇÃO aparece em Locação e Serviço, mas fica **oculto** em Venda.
- [ ] Local de entrega mostra o nome da unidade do cliente + endereço, sem repetir o nome do cliente.
- [ ] Campos opcionais ausentes (ex. sem horário de retirada) não deixam linhas vazias estranhas no PDF.

## 8. Emissão, versionamento e imutabilidade

- [ ] Emitir sem nenhuma parcela configurada é bloqueado com mensagem clara.
- [ ] Emitir com soma de parcelas divergente do total é bloqueado.
- [ ] Emitir com soma exata funciona e baixa o PDF automaticamente.
- [ ] Depois de emitida, a versão mostra badge "Emitida" e os campos ficam somente leitura.
- [ ] Editar qualquer coisa (item, condição, parcela) numa proposta já emitida cria uma nova versão (badge "Rascunho", rótulo "— Versão 2") automaticamente — sem precisar clicar em nenhum botão de "nova versão".
- [ ] A versão antiga permanece exatamente como foi emitida (PDF, parcelas, dados) mesmo depois da nova versão existir.
- [ ] Reabrir/recarregar a página sozinha nunca cria uma versão nova.

## 9. Snapshot / imutabilidade documental

- [ ] Depois de emitida, alterar o cadastro do cliente (nome, endereço, telefone, e-mail) **não** muda o PDF já emitido.
- [ ] Alterar "Dados da empresa" (Locus) depois da emissão **não** muda o PDF já emitido.
- [ ] Alterar o nome de exibição do vendedor depois da emissão **não** muda o PDF já emitido.
- [ ] Baixar o PDF de uma versão emitida sempre devolve o mesmo arquivo/conteúdo, nunca um recálculo ao vivo.

## 10. Local e data

- [ ] Rodapé mostra "Cidade - UF, DD de mês de AAAA" com a cidade/UF configurada da Locus.
- [ ] A data usada é sempre a data real de emissão daquela versão (nunca a data de hoje ao reabrir/baixar de novo).

## 11. Identificação das partes / rodapé

- [ ] Aparecem "PROPONENTE" (Locus) e "CLIENTE", sem nenhuma menção a aceite/assinatura eletrônica obrigatória.
- [ ] Aviso de que o documento não constitui aceite/fechamento aparece no rodapé.

## 12. Proposta ≠ Contrato

- [ ] Gerar/emitir a Proposta nunca marca a Oportunidade como ganha.
- [ ] Gerar/emitir a Proposta nunca cria um `Contract`/move equipamento.
- [ ] Fluxo de Venda continua funcionando sem nenhum campo de Locação (evento/responsável) causando poluição visual.

## 13. PDF — aspectos gerais

- [ ] PDF permite múltiplas páginas quando o conteúdo não cabe em uma — nenhuma tabela é cortada no meio de uma linha.
- [ ] Layout é legível, com identidade visual própria do LocusHub (não uma cópia literal do modelo de referência).

## 14. Permissões

- [ ] Usuário sem `crm.change_opportunities` não consegue adicionar/editar/remover parcela (nem por POST direto).
- [ ] Usuário sem `crm.issue_proposal_documents` não consegue emitir a Proposta.
- [ ] Nenhuma tela nova de permissão foi necessária — reaproveita o catálogo já existente.

## 15. Histórico e anexos

- [ ] PDF emitido aparece na aba "Anexos" da Oportunidade, com download protegido (nunca link direto de `/media/`).
- [ ] Aba "Histórico" registra a emissão de cada versão.
