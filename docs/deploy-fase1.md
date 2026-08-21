# Deploy de validação — Fase 1 (Patrimônio Digital)

**Base:** commit `e93abd3`, tag `fase-1-concluida`. `Especificação Técnica v1.0`, seções 9, 10, 14, 17, 19, 22.
**Objetivo deste documento:** colocar a Fase 1, já congelada, no ar no VPS da Locus para validação real — sem alterar nenhuma regra de negócio nem código de aplicação. Tudo aqui é infraestrutura/operação; a infraestrutura de deploy (Dockerfile, docker-compose.yml, docker/nginx.conf, docker/entrypoint.sh, config/settings/prod.py) já existe no repositório desde o primeiro commit e não foi alterada para produzir este documento — o que segue é o procedimento para usá-la corretamente, mais os pontos que exigem atenção humana.

---

## 1. Checklist de pré-deploy

Antes de tocar no VPS:

- [ ] `git status` limpo, `HEAD` na tag `fase-1-concluida` (commit `e93abd3`) ou branch principal apontando para o mesmo commit.
- [ ] `python -m pytest -q` → 96/96 passando localmente (repetir a mesma verificação já feita nesta engenharia; não pular por já ter passado antes).
- [ ] `python manage.py makemigrations --check` sem pendências.
- [ ] `.env.example` revisado — é só um molde; o `.env` real de produção **nunca** é uma cópia direta dele sem editar (ver seção 3).
- [ ] Nomes comerciais finais de `9PRO`, `9PRO2`, `6PRO` decididos, se algum equipamento desses modelos for cadastrado/etiquetado no primeiro lote de validação (especificação, seção 23 — não bloqueia o deploy em si, só a emissão de etiqueta correta desses 3 modelos específicos).
- [ ] DNS: acesso ao painel de DNS de `locuslocacoes.com.br` disponível para criar o registro do subdomínio (seção 3).
- [ ] Acesso SSH ao VPS HostGator (NVMe 4 — 2 vCPU/4GB/100GB) confirmado, com Docker e Docker Compose instalados (`docker --version`, `docker compose version`).
- [ ] Firewall do VPS liberando só `22` (SSH), `80` e `443` — nenhuma outra porta exposta publicamente (em particular, a porta `5432` do Postgres **não** deve ficar acessível de fora; o `docker-compose.yml` de produção já não publica essa porta para o host, só a expõe dentro da rede interna do Compose — confirmar isso no VPS com `docker compose ps` depois do deploy, não deve aparecer `0.0.0.0:5432` em lugar nenhum).
- [ ] Acesso SSH ao VPS restrito a chave pública (senha desabilitada em `/etc/ssh/sshd_config`), se ainda não estiver.

## 2. Variáveis de ambiente de produção

O `.env` real fica **só no VPS**, nunca no repositório (já está no `.gitignore`). Ele é lido via `env_file: .env` pelo `docker-compose.yml` e repassado como variável de ambiente real para o container `web`.

| Variável | Valor em produção | Por quê |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` | **O item mais importante desta tabela.** `manage.py` (usado pelo `migrate`/`collectstatic` no `entrypoint.sh`) cai em `config.settings.dev` por padrão se esta variável não estiver definida — `config/wsgi.py` (usado pelo Gunicorn) tem um padrão seguro (`prod`), mas só se a variável estiver *ausente*; se alguém copiar o `.env.example` sem editar essa linha, ela existe com o valor errado (`dev`) e o Gunicorn também passa a servir com `DEBUG=True`. Confirmar este valor é o primeiro passo do teste pós-deploy (seção 9). |
| `DJANGO_SECRET_KEY` | chave nova, gerada só para produção | Nunca reaproveitar a chave de dev. Gerar com `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`. |
| `DJANGO_DEBUG` | `False` | `config/settings/prod.py` já força `DEBUG = False` incondicionalmente, independente desta variável — mas mantenha `False` aqui por clareza operacional. |
| `DJANGO_ALLOWED_HOSTS` | `estoque.locuslocacoes.com.br` | Sem `localhost`/`127.0.0.1` em produção. `prod.py` recusa subir (`RuntimeError`) se esta variável vier vazia. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://estoque.locuslocacoes.com.br` | Precisa do esquema `https://` explícito. |
| `DJANGO_SECURE_COOKIES` | `True` | `prod.py` já força `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE = True` incondicionalmente — esta variável só importa se algum dia rodar `config.settings.base` fora de dev/prod; mantenha `True` por consistência. |
| `DJANGO_SECURE_SSL_REDIRECT` | `True` | Redireciona HTTP → HTTPS automaticamente (`prod.py`). |
| `SITE_BASE_URL` | `https://estoque.locuslocacoes.com.br` | **Crítico para os QR Codes.** É o valor gravado/usado para montar a URL permanente que cada etiqueta aponta (seção 14) — errar isso aqui gera etiquetas com link errado, sem forma de corrigir em massa depois sem reemitir. Conferir 3 vezes antes do primeiro cadastro real. |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | próprios de produção | Nunca os mesmos de dev. Senha forte, gerada (ex.: `openssl rand -base64 32`). |
| `DB_HOST` | `db` | Nome do serviço no `docker-compose.yml` — não mude para IP/hostname externo; o Postgres de produção roda no mesmo Compose (seção 4). |
| `DB_PORT` | `5432` | Porta interna do container, não exposta ao host. |
| `AXES_FAILURE_LIMIT` | `5` (ou o que a Locus decidir) | Já documentado no `.env.example`. |
| `AXES_COOLOFF_MINUTES` | `30` (ou o que a Locus decidir) | Idem. |

**Não existe ainda** variável de e-mail transacional (`EMAIL_HOST`/`EMAIL_PORT`/`EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD`) porque o provedor (Mailgun/Resend/SES) segue sem decisão — pendência já registrada desde o relatório de fechamento da Fase 1 e confirmada na auditoria. Sem isso, `config/settings/prod.py` usa o backend SMTP padrão do Django sem host configurado: **a recuperação de senha por e-mail não vai funcionar neste primeiro deploy de validação** até essa decisão ser tomada e a variável ser adicionada. Não é um bloqueador para validar o resto da Fase 1 (login com senha já cadastrada, cadastro, QR, etc.), só um limite conhecido deste primeiro deploy — não é algo a "implementar" agora, é a mesma pendência já reportada, aqui só reconfirmada no contexto de deploy.

## 3. Domínio/subdomínio

Decisão já confirmada na especificação (seção 22): subdomínio `estoque.locuslocacoes.com.br`, para não mexer no site institucional que já ocupa o domínio raiz.

1. No painel de DNS de `locuslocacoes.com.br`, criar um registro `A` para `estoque` apontando para o IP público do VPS. (Se preferir CNAME por algum motivo de infraestrutura da HostGator, tudo bem — o importante é que `estoque.locuslocacoes.com.br` resolva para o VPS.)
2. Propagação de DNS pode levar de minutos a algumas horas — confirmar com `dig estoque.locuslocacoes.com.br` ou `nslookup estoque.locuslocacoes.com.br` antes de tentar emitir o certificado TLS (o Let's Encrypt precisa que o domínio já resolva para o servidor).

## 4. PostgreSQL de produção

Já definido em `docker-compose.yml`: um container `postgres:16` dedicado, com volume nomeado (`locus_db_data`) para persistência, sem porta publicada para o host (só acessível pelos outros containers do mesmo Compose, via `DB_HOST=db`), com healthcheck (`pg_isready`) que o serviço `web` respeita antes de subir (`depends_on: condition: service_healthy`).

Nada a configurar manualmente além de `DB_NAME`/`DB_USER`/`DB_PASSWORD` no `.env` — o container do Postgres já nasce configurado com esses valores (variáveis `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` no `docker-compose.yml`, lidas do mesmo `.env`). `python manage.py migrate` roda automaticamente a cada subida do container `web` (`docker/entrypoint.sh`).

Se, no futuro, a Locus preferir um Postgres gerenciado fora do Compose (RDS-like, ou o próprio Postgres do VPS instalado direto no host): só trocar `DB_HOST`/`DB_PORT` no `.env` e remover o serviço `db` do compose — nenhuma mudança de código, a aplicação já é agnóstica a onde o Postgres roda.

## 5. Gunicorn

Já configurado em `docker/entrypoint.sh`: `gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3`, rodando dentro do container `web`, nunca exposto diretamente à internet (só o Nginx fala com ele, via rede interna do Compose, `proxy_pass http://web:8000`).

3 workers é um ponto de partida razoável para 2 vCPU (regra geral `(2 × núcleos) + 1` sugeriria 5; comece com 3, observe uso de CPU/memória no primeiro dia real de uso e ajuste `--workers` no `entrypoint.sh` depois, se necessário — não é algo para decidir às cegas antes de ter uso real).

## 6. Nginx

Já configurado em `docker/nginx.conf`: dois blocos `server` — porta 80 redirecionando tudo para HTTPS (exceto o desafio ACME do certbot), porta 443 com TLS terminando ali, arquivos estáticos e media servidos diretamente pelo Nginx (`/static/`, `/media/`, via os volumes compartilhados com o container `web`), e proxy reverso para o Gunicorn em `/`.

`client_max_body_size 20M` já está definido (relevante quando fotos/anexos entrarem, mas inofensivo já ativo agora).

Nada a alterar aqui para este deploy — a única coisa a **conferir** é se `server_name` no arquivo bate exatamente com o subdomínio decidido (já está `estoque.locuslocacoes.com.br`, conforme seção 22 da especificação).

## 7. HTTPS

Certbot já está no `docker-compose.yml` como serviço dedicado, com volumes compartilhados com o Nginx (`certbot_conf`, `certbot_www`).

**Emissão inicial** (rodar uma vez, depois que o DNS já estiver resolvendo e o Nginx já estiver de pé servindo HTTP na porta 80 — o desafio ACME passa por `http://estoque.../.well-known/acme-challenge/`):

```bash
docker compose up -d nginx
docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  -d estoque.locuslocacoes.com.br \
  --email seu-email@locuslocacoes.com.br --agree-tos --no-eff-email
docker compose restart nginx
```

**Renovação automática** (o certificado do Let's Encrypt expira a cada 90 dias) — o compose não roda isso sozinho, precisa de um cron no host do VPS:

```bash
# crontab -e (no host, fora dos containers)
0 3 * * * cd /caminho/do/repositorio && docker compose run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload
```

## 8. Static e media

`STATIC_ROOT`/`MEDIA_ROOT` já apontam para diretórios dentro do container `web` (`config/settings/base.py`), montados como volumes nomeados (`static_volume`, `media_volume`) compartilhados só-leitura com o Nginx. `docker/entrypoint.sh` já roda `collectstatic --noinput` a cada subida do container — nenhum passo manual necessário.

`whitenoise` está listado em `requirements/prod.txt` mas não está conectado no `MIDDLEWARE` nem em `STATICFILES_STORAGE` — não é usado, porque o Nginx já serve os estáticos diretamente do volume. Não é um bug (o Nginx cobre o mesmo papel), é só uma dependência instalada sem uso; não precisa de ação para este deploy, registrando aqui só para não gerar confusão numa auditoria futura.

## 9. Configuração segura de produção — o que já está garantido e o que confirmar

Já garantido por `config/settings/prod.py` e `base.py`, **independente do que estiver no `.env`**, sempre que `DJANGO_SETTINGS_MODULE=config.settings.prod` estiver de fato ativo:

- `DEBUG = False` (hardcoded em `prod.py`, não depende de variável).
- `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`, ambos `HttpOnly`.
- `SECURE_SSL_REDIRECT = True`, HSTS de 30 dias com `includeSubDomains` e `preload`.
- `X_FRAME_OPTIONS = "DENY"`.
- Sobe travado se `ALLOWED_HOSTS` vier vazio (falha rápida, não sobe inseguro por omissão).
- Senha com Argon2, `django-axes` contra força bruta (username OU IP), Postgres com `SELECT FOR UPDATE` real.

O que exige confirmação humana no dia do deploy (não é automático):

- **`DJANGO_SETTINGS_MODULE=config.settings.prod` realmente presente e correto no `.env`** — é a única forma de todo o resto acima entrar em vigor. Ver seção 2 e o teste pós-deploy (seção 11, item 1).
- `.env` do VPS com permissão de leitura restrita (`chmod 600 .env`, dono = usuário que roda o Docker) — evita leitura por outro usuário/processo do mesmo servidor.
- Backup automático agendado (seção 10) — sem isso, "produção" ainda depende de um único ponto de falha (disco do VPS).

## 10. Criação do primeiro usuário administrador

Isto precisa de um cuidado específico deste projeto: `python manage.py createsuperuser` cria um usuário com `is_superuser=True`/`is_staff=True`, mas o campo de perfil de negócio (`role`, usado pela matriz de permissões da seção 11) **não** é setado por esse comando — nasce com o valor padrão do modelo, `CONSULTA`. Um `is_superuser` passa nas checagens de permissão de *backend* (`RoleRequiredMixin`/`roles_required()` sempre liberam superusuário, é a válvula de segurança padrão do Django), mas parte da interface — a ficha de equipamento (`detail_private.html`: alterar status/condição, editar dados, reclassificar, reemitir) e a listagem (`list.html`: botão "Novo equipamento", coluna de QR) — decide o que **mostrar** checando só `role`, sem o mesmo "ou superusuário" que o menu principal (`base.html`) já tem. Ou seja: logando só com `createsuperuser`, o primeiro admin acessaria as telas certas se soubesse a URL de cor, mas veria uma interface capada, sem os botões de ação. Por isso o passo de ajustar `role` abaixo não é opcional.

```bash
docker compose exec web python manage.py createsuperuser
# username, e-mail, senha forte — anotar em local seguro (gestor de senhas da Locus)

docker compose exec web python manage.py shell -c "
from apps.accounts.models import User, Role
u = User.objects.get(username='SUBSTITUA_PELO_USERNAME_CRIADO_ACIMA')
u.role = Role.ADMIN
u.save(update_fields=['role'])
print(f'{u.username}: role={u.role}, is_superuser={u.is_superuser}')
"
```

A partir daí, esse usuário usa a tela própria de gestão de usuários (`/contas/usuarios/`) para cadastrar as próximas contas da equipe (Administrador/Administrativo/Operacional/Consulta) — não precisa mais de `createsuperuser`/shell para ninguém depois do primeiro.

## 11. Backup antes e depois do deploy

Ainda não existe automação de backup no repositório (item da seção 17 da especificação, sinalizado desde o relatório de fechamento como pendência de infraestrutura, não de código). Para este primeiro deploy de validação, o procedimento é manual:

**Antes do deploy** (o banco de produção, no primeiro deploy, está vazio — mas o hábito começa aqui, para todo deploy futuro):

```bash
docker compose exec -T db pg_dump -U ${DB_USER} ${DB_NAME} | gzip > backup-pre-deploy-$(date +%Y%m%d-%H%M).sql.gz
```

**Depois do deploy**, assim que os dados de validação (equipamentos de teste, ou já os primeiros reais) estiverem cadastrados:

```bash
docker compose exec -T db pg_dump -U ${DB_USER} ${DB_NAME} | gzip > backup-pos-deploy-$(date +%Y%m%d-%H%M).sql.gz
```

Copiar os dois arquivos para fora do VPS (download local, ou já para o armazenamento externo que a Locus escolher — Backblaze B2 via `rclone` é a opção citada na especificação, seção 17, ainda não decidida). Não deixar backups só no mesmo disco do VPS.

**Teste de restore** (fazer pelo menos uma vez, num ambiente separado — nunca testar restore contra o banco de produção):

```bash
gunzip -c backup-pos-deploy-*.sql.gz | docker compose exec -T db psql -U ${DB_USER} ${DB_NAME}
```

Rotina diária automática (cron + retenção 30–90 dias) segue como pendência de infraestrutura para logo após este primeiro deploy — não bloqueia a validação, mas não deve ser esquecida depois que dados reais começarem a entrar.

## 12. Procedimento de rollback

Como este é o **primeiro** deploy (sem usuários reais dependendo do sistema ainda), o rollback mais simples é derrubar tudo e recomeçar do zero quando o problema for descoberto cedo:

```bash
docker compose down
# corrigir o que precisar (DNS, .env, etc.)
docker compose up -d --build
```

Se o problema aparecer **depois** que já há dados reais cadastrados (deploys seguintes a este):

1. **Código:** `git checkout <tag-ou-commit-anterior-conhecido-bom>` no VPS, depois `docker compose up -d --build`. Como a Fase 1 está tagueada (`fase-1-concluida`), sempre existe um ponto conhecido-bom para voltar.
2. **Banco:** só restaurar backup se a migration do deploy problemático já tiver rodado e for destrutiva/incompatível com o código anterior — o que não é o caso de nenhuma migration existente hoje (todas são aditivas). Se restaurar for necessário: `docker compose down`, apagar o volume `locus_db_data` (**só se já houver um backup confirmado e íntegro**), subir o `db` sozinho, restaurar (`gunzip -c backup.sql.gz | docker compose exec -T db psql -U ${DB_USER} ${DB_NAME}`), depois subir o resto.
3. Nunca fazer rollback de código sem verificar se as migrations do commit-alvo são compatíveis com o estado atual do banco — em caso de dúvida, restaurar o backup pré-deploy correspondente aquele commit em vez de tentar migrar "para trás".

## 13. Teste pós-deploy (verificação técnica, no servidor)

Rodar nesta ordem, direto no VPS, antes de liberar para a equipe da Locus:

1. **Confirmar que é `prod`, não `dev`:**
   ```bash
   docker compose exec web python manage.py shell -c "from django.conf import settings; print(settings.DEBUG, settings.SETTINGS_MODULE)"
   ```
   Precisa imprimir `False config.settings.prod`. Se imprimir `True`, **parar** — o `.env` está errado (ver seção 2), corrigir antes de continuar.
2. `docker compose ps` → todos os serviços (`db`, `web`, `nginx`) `healthy`/`running`; confirmar que não há `0.0.0.0:5432` em nenhuma linha.
3. `curl -I http://estoque.locuslocacoes.com.br/` → `301` para `https://`.
4. `curl -I https://estoque.locuslocacoes.com.br/` → `200` (ou `302` para o login, se a rota raiz exigir autenticação), certificado válido (sem `-k` no curl).
5. Acessar `/contas/login/` no navegador, logar com o usuário administrador criado na seção 10.
6. Conferir que a interface do administrador mostra os links de "Categorias", "Modelos", "Importar planilha", "Usuários" (confirma que o `role=ADMIN` da seção 10 foi aplicado corretamente).
7. Cadastrar um equipamento de teste (`/equipamentos/novo/`), confirmar que o patrimônio sai no formato `LOC-{CODE}-{SEQUENCE}`.
8. Baixar o QR/etiqueta desse equipamento de teste.
9. `docker compose logs web --tail=100` → sem tracebacks/erros na sequência de testes acima.
10. Rodar `python manage.py seed_catalog` se ainda não tiver sido rodado neste ambiente (idempotente, seguro rodar de novo).

## 14. Passo a passo operacional — visão geral condensada

Ordem completa, do zero, referenciando as seções acima:

1. Provisionar VPS, Docker/Docker Compose, firewall (`22`/`80`/`443`) — checklist seção 1.
2. Criar o registro DNS do subdomínio e esperar propagar — seção 3.
3. Clonar o repositório no VPS, `git checkout` na tag `fase-1-concluida`.
4. Criar o `.env` real de produção — seção 2 (**conferir `DJANGO_SETTINGS_MODULE=config.settings.prod` três vezes**).
5. `docker compose up -d db` — subir só o banco primeiro, esperar `healthy`.
6. `docker compose up -d --build web` — sobe migrations + collectstatic automaticamente (`entrypoint.sh`), depois o Gunicorn.
7. `docker compose up -d nginx` — Nginx sobe servindo HTTP (o bloco 443 vai falhar até o certificado existir; tudo bem, o próximo passo resolve).
8. Emitir o certificado TLS — seção 7. Reiniciar o Nginx.
9. Configurar o cron de renovação do certificado no host — seção 7.
10. Criar o primeiro usuário administrador e corrigir o `role` — seção 10.
11. Rodar `seed_catalog` se ainda não rodou.
12. Backup pré-validação — seção 11.
13. Rodar o teste pós-deploy técnico completo — seção 13.
14. Só então: teste de validação real no celular — seção 15.
15. Backup pós-validação — seção 11.

## 15. Checklist de validação real no celular

Com dados de teste já no ar (equipamento de teste cadastrado no passo 7 da seção 13), fora da rede Wi-Fi do escritório/VPS (usar dados móveis 4G/5G — o critério de aceite da especificação, seção 20, item 10, é especificamente sobre conexão móvel real, não Wi-Fi):

- [ ] Abrir a câmera do celular e apontar para o QR impresso/exibido na tela do equipamento de teste (ou escanear direto a imagem baixada, se a etiqueta ainda não foi impressa fisicamente).
- [ ] Confirmar que o QR abre `https://estoque.locuslocacoes.com.br/equipamentos/LOC-...` — com **cadeado/HTTPS válido** no navegador do celular, sem aviso de certificado.
- [ ] Cronometrar o tempo entre o scan e a página carregada — critério de aceite: **menos de 2 segundos** numa 4G comum.
- [ ] Sem estar logado no celular: confirmar que a ficha pública mostra só empresa/categoria/modelo/patrimônio e o convite para login — **sem** cliente, valor de aquisição ou observações internas.
- [ ] Logar pelo celular (`/contas/login/`) com um usuário de teste de cada perfil, um de cada vez, e confirmar visualmente:
  - [ ] Administrador: vê tudo, inclusive valor de aquisição e os botões de ação (status, condição, editar, reclassificar, reemitir).
  - [ ] Administrativo: vê valor de aquisição e a maioria das ações, mas não reclassificar/reemitir.
  - [ ] Operacional/Técnico: **não** vê valor de aquisição nem fornecedor; vê e consegue usar alterar status/condição.
  - [ ] Consulta: só visualiza, nenhum botão de ação, e sem valor de aquisição.
- [ ] Testar o layout em pelo menos duas larguras de tela reais (um celular e, se possível, um tablet ou celular grande) — a especificação pede mobile-first para a ficha do equipamento; usar o deploy real para confirmar visualmente, já que isso não é coberto por teste automatizado.
- [ ] Tentar logar errado propositalmente (senha errada) 5+ vezes seguidas com o mesmo usuário, pelo celular, e confirmar que o `django-axes` bloqueia (mensagem de bloqueio, não só "senha incorreta" repetido indefinidamente).
- [ ] Desligar o Wi-Fi do celular por completo antes de repetir o teste do QR, para garantir que é mesmo a rede móvel sendo testada, não a rede do escritório.

Se tudo isso passar, a Fase 1 está validada em produção real, não só em ambiente de teste — é o critério que faltava para fechar em definitivo o item 10 da seção 20 da especificação (o único critério de aceite que não podia ser verificado antes do deploy).
