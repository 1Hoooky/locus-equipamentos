# Auditoria final de arquitetura — Fase 1 (Patrimônio Digital)

**Data:** 21/08/2026
**Commit auditado:** `5d5f63d` (branch principal, working tree limpo)
**Base de comparação:** `Especificação Técnica v1.0` (`docs/especificacao-tecnica-v1.0.md`)
**Escopo desta auditoria:** confirmar se a Fase 1 pode ser declarada concluída e congelada, sem propor nem implementar nada de Fase 2/3.

Esta auditoria não alterou código. É um registro de estado, ponto a ponto contra a especificação, para servir de base ao congelamento (tag `fase-1-concluida`) e a qualquer decisão futura sobre o que abrir na Fase 2.

---

## 1. Estado do repositório no momento do congelamento

- Working tree limpo, sem alterações pendentes, `HEAD` em `5d5f63d`.
- `python manage.py makemigrations --check` → sem migrações pendentes.
- `python manage.py migrate` → aplicado sem erros contra PostgreSQL 16 real.
- `python manage.py check` → sem erros.
- `python -m pytest -q` → **88 testes, 88 passaram, 0 falharam**, contra PostgreSQL real (nenhum teste usa SQLite ou mocka o banco).
- Banco de desenvolvimento confirmado em estado limpo antes do congelamento (0 `Equipment`, 0 `StatusHistory`, 0 `ConditionHistory`, 9 `EquipmentModel`, 2 `Category`, 1 usuário admin).
- `ruff check` aponta 39 ocorrências, todas pré-existentes (`RUF012`, listas/dicts mutáveis em `class Meta`), confirmadas via `git stash` como estilo já aceito no projeto antes desta auditoria — nenhuma nova.

## 2. Checklist — seção 12 (Telas da Fase 1)

A seção 20 (critérios de aceite) fala em "as 12 telas da seção 12", mas a tabela da própria seção 12 lista **13** linhas distintas. É uma inconsistência interna menor da especificação, não do código — registrada aqui para o caso de vir a gerar confusão numa revisão futura do documento de referência. A checagem abaixo segue a tabela real (13 linhas).

| # | Tela (seção 12) | Rota real | Status | Cobertura de teste |
|---|---|---|---|---|
| 1 | Login | `accounts:login` (`/contas/login/`) | Implementada, protegida por `django-axes` | `test_axes_lockout.py` |
| 2 | Recuperação de senha | `accounts:password_reset` + `_done` + `_confirm` + `_complete` (4 rotas, views padrão do Django) | Implementada e navegável; e-mail via console backend em dev | **Sem teste automatizado dedicado** (ver seção 5) |
| 3 | Listagem/busca de equipamentos | `equipment:list` | Implementada, com filtros (status, condição, categoria, modelo) + busca livre | `test_equipment_crud_views.py::EquipmentListFiltersTest` |
| 4 | Ficha do equipamento — pública | `equipment:detail` (não autenticado) | Implementada, sem dados sensíveis | `test_public_detail_view.py` |
| 5 | Ficha do equipamento — autenticada | `equipment:detail` (autenticado) | Implementada, com ações rápidas por perfil | `test_public_detail_view.py`, `test_equipment_crud_views.py` |
| 6 | Cadastro/edição de equipamento | `equipment:create` / `equipment:update` | Implementada; patrimônio não editável; fotos ainda não (ver seção 5) | `EquipmentCreateViewTest`, `EquipmentUpdateViewTest` |
| 7 | Cadastro/edição de categoria | `catalog:category_list/create/update` | Implementada | `test_catalog_views.py::CategoryViewsTest` |
| 8 | Cadastro/edição de modelo | `catalog:model_list/create/update` | Implementada, `code` trava após 1º equipamento vinculado | `test_catalog_views.py::EquipmentModelViewsTest` |
| 9 | Reclassificação de modelo | `equipment:reclassify` | Implementada, motivo obrigatório, preserva patrimônio | `EquipmentReclassifyViewTest` |
| 10 | Geração/download de QR e etiqueta | `qrcodes:qr_png`, `label_pdf`, `label_batch` | Implementada, individual e em lote | `test_qr_and_labels.py` |
| 11 | Exportação de dados | `equipment:export` | Implementada, respeita filtros aplicados | `test_export.py` |
| 12 | Importação da planilha legada | `equipment:import_upload/_review/_summary` | Implementada, validada de ponta a ponta contra a planilha real (306 linhas) | `test_legacy_import.py` |
| 13 | Gestão de usuários | `accounts:user_list/create/update` | Implementada, com trava de autodesativação | `test_user_management.py` |

**Adição deliberada além da tabela:** a tela de **reemissão excepcional de patrimônio** (`equipment:supersede`) não é uma linha própria da seção 12 — ela aparece descrita como ação nas seções 8 e 13-C. Foi implementada como tela dedicada nesta etapa por instrução explícita do usuário ("fechamento da Fase 1", item 2). Registro aqui apenas para deixar claro que não é scope creep não solicitado: é a materialização de um requisito que já existia em texto, formalizada como tela própria.

**Resultado:** 13/13 linhas da tabela real cobertas por rota funcional; 12/13 com teste automatizado dedicado; 1/13 (recuperação de senha) implementada mas sem teste (detalhe na seção 5).

## 3. Checklist — seção 11 (Matriz de permissões)

| Ação (seção 11) | Especificação | Constante em `permissions.py` | Confere? | Teste |
|---|---|---|---|---|
| Gerenciar usuários e permissões | Admin | `CAN_MANAGE_USERS = (ADMIN,)` | Sim | `test_permissions.py`, `test_user_management.py` |
| Cadastrar/editar categorias e modelos | Admin, Administrativo | `CAN_MANAGE_CATALOG` | Sim | `test_catalog_views.py` |
| Editar `code` de modelo com equipamentos / reemitir patrimônio | Admin | `CAN_EDIT_LOCKED_MODEL_CODE`, `CAN_SUPERSEDE_EQUIPMENT` | Sim | `test_catalog_views.py`, `EquipmentSupersedeViewTest` |
| Reclassificar modelo | Admin | `CAN_RECLASSIFY_EQUIPMENT_MODEL` | Sim | `EquipmentReclassifyViewTest` |
| Cadastrar/editar equipamento | Admin, Administrativo | `CAN_MANAGE_EQUIPMENT` | Sim | `EquipmentCreateViewTest`, `EquipmentUpdateViewTest` |
| Ver valor de aquisição / dados financeiros | Admin, Administrativo | `CAN_VIEW_ACQUISITION_VALUE` | Regra existe e é aplicada na *tela* (`detail_private.html`, bloco `{% if user.is_administrativo_ou_superior %}` em torno de fornecedor/data/valor de aquisição) | **Sem teste automatizado dedicado** (ver seção 5) |
| Registrar manutenção/higienização/movimentação | Admin, Administrativo, Operacional | `CAN_REGISTER_OPERATIONS` | Constante definida, sem uso ainda — correto: é ação de Fase 2 | N/A (fora do escopo desta fase) |
| Alterar condição/status | Admin, Administrativo, Operacional | `CAN_CHANGE_STATUS_CONDITION` | Sim | `EquipmentChangeStatusConditionViewTest` |
| Adicionar fotos | Admin, Administrativo, Operacional | `CAN_ADD_PHOTOS` | Constante definida, sem uso — `apps/attachments` ainda é esqueleto (ver seção 5) | N/A |
| Consultar equipamento e histórico | Todos os perfis | `CAN_VIEW_EQUIPMENT` | Sim | `test_public_detail_view.py`, `test_permissions.py` |
| Exportar dados | Admin, Administrativo | `CAN_EXPORT_DATA` | Sim | `test_export.py` |
| Importar planilha legada | Admin | `CAN_IMPORT_LEGACY_SPREADSHEET` | Sim | `test_legacy_import.py` |

**Resultado:** as 12 linhas da matriz têm uma constante de permissão correspondente e correta em código; as 2 linhas de escopo de Fase 2 (manutenção/higienização/movimentação, fotos) estão deliberadamente não usadas ainda, o que é o comportamento esperado nesta fase. Das 10 linhas efetivamente ativas na Fase 1, 9 têm teste automatizado cobrindo o bloqueio por perfil; a exceção (valor de aquisição/dados financeiros) é aplicada corretamente na interface mas não tem teste que prove que um usuário Operacional ou Consulta, acessando a ficha autenticada, não recebe esse dado na resposta HTTP — o teste existente (`test_authenticated_page_shows_full_data`) só cobre o perfil Admin vendo o dado, não os perfis que deveriam ficar de fora vendo a ausência dele.

## 4. Checklist — seção 20 (Critérios de aceite da Fase 1)

| # | Critério | Situação |
|---|---|---|
| 1 | Novo equipamento recebe patrimônio no formato correto, `model_sequence` coerente | Atendido — `create_equipment()`, testado |
| 2 | Cadastros concorrentes do mesmo modelo nunca duplicam `model_sequence` | Atendido — teste de concorrência com 12 threads simultâneas, zero duplicidade |
| 3 | Editar modelo de um equipamento existente nunca altera `patrimonio` | Atendido — `EquipmentUpdateForm` nem expõe o campo `model`; só `reclassify_model()`/`supersede_equipment()` tocam nisso, e preservam/renovam o patrimônio conforme a regra |
| 4 | `EquipmentModel.code` não editável após 1º equipamento vinculado | Atendido — testado inclusive tentando forçar o valor via POST bruto |
| 5 | Página pública nunca expõe cliente, valor, manutenção ou dado interno | Atendido — testado |
| 6 | Os 305 equipamentos da planilha atual importados com `legacy_code`, `model_id` corretos, novo patrimônio | Atendido — validado de ponta a ponta contra a planilha real (306 linhas; a especificação registra "305", a diferença de 1 linha é da própria contagem original da planilha e não afeta o critério) |
| 7 | Exportação CSV/Excel reproduz `patrimonio`, `model`, `status`, `condition`, `legacy_code` de equipamentos ativos | Atendido — testado |
| 8 | Admin cadastra modelo novo e gera patrimônios sem alteração de código-fonte ou deploy | Atendido — cadastro de modelo é tela própria (`catalog:model_create`), não depende de fixture nem de código |
| 9 | As 12 (13) telas da seção 12 implementadas e navegáveis nos perfis corretos, matriz da seção 11 coberta por testes | **Atendido com uma ressalva**: todas as telas existem e navegam corretamente nos perfis certos; a matriz de acesso a *telas* está 100% coberta por teste, mas a regra de visibilidade de *dado* (valor de aquisição, dentro de uma tela que outros perfis também acessam) não tem teste dedicado — ver seção 5, item 2 |
| 10 | QR impresso, escaneado no celular, abre a ficha pública em <2s numa 4G comum | Não é um critério verificável em ambiente de sandbox/CI — depende de rede real e hospedagem em produção. Tecnicamente atendível (a ficha pública é uma view simples sem consultas pesadas), mas **não pode ser confirmado sem o deploy em produção**, que ainda não ocorreu |

**Resultado:** 8/10 critérios plenamente atendidos e verificados; 1/10 (critério 9) atendido com uma lacuna de teste pontual e objetiva; 1/10 (critério 10) só é verificável após o deploy em produção, que está fora do escopo desta auditoria de código.

## 5. Pendências objetivas encontradas nesta auditoria

Nenhuma destas pendências é um bug de comportamento — em todos os casos, a regra de negócio está implementada e correta. São lacunas de **cobertura de teste** ou **itens já sinalizados como pendentes de Fase 1** desde o relatório de validação anterior. Nenhuma foi corrigida nesta auditoria, conforme o escopo pedido ("monta uma auditoria" — não "corrija").

1. **Recuperação de senha sem teste automatizado.** As 4 rotas existem, usam as views padrão do Django (`django.contrib.auth.views`, já testadas pelo próprio framework) e os templates estão implementados. O que falta é um teste de integração no projeto confirmando o fluxo completo (solicitar → receber link no backend de console/e-mail → confirmar → logar com a senha nova) e, à parte, a decisão de provedor de e-mail transacional de produção (Mailgun/Resend/SES — já sinalizada como pendência no relatório anterior, segue em aberto).
2. **Visibilidade de valor de aquisição sem teste automatizado.** A regra existe e está correta no template (`detail_private.html`), mas não há teste HTTP confirmando que um usuário Operacional ou Consulta, ao abrir a ficha autenticada de um equipamento, não recebe `acquisition_value`/`supplier`/`acquisition_date` na resposta.
3. **Fotos/anexos de equipamento** — `apps/attachments` continua um esqueleto vazio. Não é critério de aceite explícito da seção 20, mas é campo previsto na tela de cadastro (seção 12) e a permissão `CAN_ADD_PHOTOS` já existe sem uso. Confirmado nesta auditoria como não-bloqueante para o congelamento da Fase 1, pelos mesmos termos do relatório de fechamento anterior.
4. **E-mail transacional de produção** — dev funciona via console backend; produção depende de escolha de provedor. Não-bloqueante para o congelamento (não é critério de aceite da seção 20), mas necessário antes de considerar a recuperação de senha utilizável por usuários reais em produção.
5. **Critério de aceite #10 (QR em <2s numa 4G real)** só pode ser verificado após o deploy em produção — não há como testar isso em sandbox. Fica como item de verificação pós-deploy, não como pendência de código.
6. **Backup automático** (`pg_dump` diário + cópia externa, seção 17/19) — já documentado no `README.md` como próximo item de infraestrutura, fora do código da aplicação. Não é código, então não foi reavaliado em profundidade nesta auditoria de arquitetura — segue como pendência operacional de deploy.

Nenhuma destas 6 pendências envolve arquitetura, modelo de dados ou lógica de negócio incorreta — são todas lacunas de teste ou itens de infraestrutura/deploy já conhecidos.

## 6. Revisão de segurança e integridade de dados

- **Senhas:** Argon2 (`PASSWORD_HASHERS`, `argon2-cffi`), não o PBKDF2 padrão do Django.
- **Força bruta:** `django-axes` ativo, `AxesStandaloneBackend` antes de `ModelBackend`, `AxesMiddleware` como última entrada do `MIDDLEWARE` (posição correta, exigida pela biblioteca). Bloqueio por usuário OU por IP (`AXES_LOCKOUT_PARAMETERS` como lista plana = semântica OR, confirmado lendo o código-fonte do axes, não só a documentação). Cooloff automático, reset no login bem-sucedido. Testado com requisições HTTP reais (não com o atalho `client.login()`, que é incompatível com o backend do axes).
- **Sessão/CSRF:** cookies `HttpOnly` (sessão e CSRF) sempre ativos; `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` controláveis por `.env`, mas com **default `True`** mesmo em `base.py` — ou seja, mesmo que `prod.py` não fixasse explicitamente esses valores (e fixa), a configuração já nasceria segura por padrão. `prod.py` além disso reforça `SECURE_SSL_REDIRECT`, HSTS (30 dias, incluindo subdomínios, com preload) e falha explicitamente (`RuntimeError`) se `DJANGO_ALLOWED_HOSTS` não estiver definido — não deixa a aplicação subir em produção com `ALLOWED_HOSTS` vazio ou `"*"`.
- **Separação dev/prod:** `config/settings/base.py` (comum) + `dev.py` (DEBUG=True, e-mail console) + `prod.py` (DEBUG=False, exige envs obrigatórios, endurece cookies/HSTS) + `test.py` (novo nesta fase — herda de `dev.py`, só existe para desligar `django-axes` durante a suíte geral, já que o atalho de teste do Django não é compatível com o backend do axes; o teste dedicado do axes reativa via `override_settings`). Não existe SQLite em nenhum ambiente — a geração atômica de patrimônio depende de `SELECT FOR UPDATE`, que o SQLite não garante sob concorrência real.
- **Imutabilidade do patrimônio:** garantida em duas camadas — de aplicação (`EquipmentUpdateForm` nem expõe o campo; só `services.py` grava `model_sequence`/`patrimonio`) e de banco (`UniqueConstraint` `uniq_model_sequence_per_model`, segunda linha de defesa caso a camada de aplicação seja contornada por algum caminho não previsto).
- **Consistência de `StatusHistory`/`ConditionHistory`:** o Django admin tem `status`/`condition` como `readonly_fields`, então mesmo um superusuário usando o admin como contingência não consegue gerar uma mudança de status/condição sem passar por `change_status()`/`change_condition()` — as duas únicas funções que gravam o evento estruturado, sempre na mesma transação atômica que grava o novo valor.
- **Auditoria de campo:** `django-simple-history` em `EquipmentModel` e `Equipment`, com `SIMPLE_HISTORY_HISTORY_CHANGE_REASON_USE_TEXT_FIELD = True` (motivo sem limite de 100 caracteres — bug real da configuração padrão, corrigido na validação anterior).
- **Exposição de dados públicos:** testado automaticamente — página pública nunca inclui cliente, fornecedor, valor de aquisição ou observações internas.

Nenhum problema novo de segurança foi identificado nesta auditoria; os pontos fortes acima já vinham do relatório de validação anterior e do fechamento da Fase 1, e foram reconfirmados lendo o código atual, não apenas repetidos de memória.

## 7. Conclusão

A Fase 1 — Patrimônio Digital está **funcionalmente completa e coberta por 88 testes automatizados passando contra PostgreSQL real**. Todas as 13 telas da seção 12 existem, navegam nos perfis corretos e (com uma exceção pontual) têm teste dedicado. A matriz de permissões da seção 11 está corretamente implementada em código para as 12 ações, incluindo as 2 que ainda não têm uso ativo (corretamente reservadas para a Fase 2). 8 dos 10 critérios de aceite da seção 20 estão plenamente verificados; o 9º tem uma lacuna de teste pontual (não de comportamento) e o 10º só é verificável após o deploy em produção.

Não foi encontrado nenhum bug de comportamento, nenhuma divergência de arquitetura em relação à especificação, nem nenhum código incompleto/mock/placeholder além dos já conhecidos e documentados (fotos/anexos, e-mail transacional de produção, refinamento visual, build do Tailwind) — todos não-bloqueantes para o congelamento, pelos próprios termos da especificação (nenhum é critério de aceite explícito da seção 20).

**Recomendação:** a Fase 1 pode ser congelada nestes termos. As duas lacunas de teste identificadas nesta auditoria (recuperação de senha, visibilidade de valor de aquisição por perfil) ficam registradas como pendências pontuais e de baixo risco — nenhuma delas indica que a regra de negócio esteja errada, apenas que falta uma prova automatizada dela — e podem ser fechadas a qualquer momento sem reabrir escopo de Fase 1, a critério do usuário.
