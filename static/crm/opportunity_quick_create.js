/**
 * Drawer lateral de criação rápida de oportunidade (CRM, Funil Kanban) —
 * rodada "CRIAÇÃO RÁPIDA SEM SAIR DO FUNIL", 11/09/2026.
 *
 * Vanilla JS, mesma convenção do restante do projeto (nenhuma lib nova,
 * ver static/crm/kanban.js) — script INDEPENDENTE de kanban.js: os dois
 * só compartilham a leitura de `#kanban-board` (para a querystring de
 * filtros ativos), nunca variável/estado em comum, e cada um lê os
 * próprios elementos só pelo próprio id. Isto é deliberado — a
 * permissão de criar (`crm.add_opportunities`) e a de mudar etapa
 * (`crm.change_opportunity_stage`) são independentes; um usuário pode
 * ter só uma das duas, então os dois scripts podem existir sozinhos na
 * página.
 *
 * Único caminho de escrita: sempre `POST /crm/oportunidades/nova/` — a
 * MESMA URL/view da rota tradicional de criação
 * (apps.crm.views.OpportunityCreateView), com o cabeçalho
 * `X-Requested-With: XMLHttpRequest` para obter JSON/fragmento em vez de
 * um redirect de página inteira (idêntico ao padrão já estabelecido em
 * kanban.js para mudança de etapa). Este script NUNCA decide sozinho se
 * uma oportunidade é válida — só REAGE ao que o backend responde:
 *   - HTTP 400: o backend devolve o FRAGMENTO de campos re-renderizado
 *     (com erros bound e os valores que o usuário digitou) — o script
 *     troca o innerHTML do container de campos, sem fechar o drawer nem
 *     perder nada que já foi preenchido em outros campos;
 *   - HTTP 200 com `ok: true`: a oportunidade foi criada de verdade no
 *     banco — o script insere o HTML do card (pronto, vindo do backend
 *     via render_to_string, nunca remontado aqui) na coluna certa, só
 *     quando `matches_current_filters` confirma que ela aparece sob os
 *     filtros ativos no momento (mesma fonte de verdade do backend,
 *     nunca uma cópia da lógica de filtro em JS), e fecha o drawer.
 */
(function () {
  "use strict";

  var openLink = document.getElementById("opportunity-quick-create-open");
  var drawer = document.getElementById("opportunity-quick-create-drawer");
  var backdrop = document.getElementById("opportunity-quick-create-backdrop");
  var closeBtn = document.getElementById("opportunity-quick-create-close");
  var cancelBtn = document.getElementById("opportunity-quick-create-cancel");
  var form = document.getElementById("opportunity-quick-create-form");
  var fieldsContainer = document.getElementById("opportunity-quick-create-fields");
  var submitBtn = document.getElementById("opportunity-quick-create-submit");

  if (!openLink || !drawer || !backdrop || !closeBtn || !cancelBtn || !form || !fieldsContainer || !submitBtn) {
    return;
  }

  var board = document.getElementById("kanban-board");
  var filtersQuery = board ? board.getAttribute("data-filters-query") || "" : "";

  // Cópia "de fábrica" do fragmento de campos, tirada ANTES de qualquer
  // interação — usada para resetar o formulário depois de uma criação
  // bem-sucedida (nunca precisa de um novo round-trip ao servidor só
  // para reabrir o drawer em branco de novo).
  var pristineFieldsHtml = fieldsContainer.innerHTML;

  var isSubmitting = false;
  var pendingDiscardConfirm = false;
  var discardTimer = null;
  var CANCEL_DEFAULT_LABEL = cancelBtn.textContent;

  // -------------------------------------------------------------------
  // Toast simples — mesmo componente visual de kanban.js
  // (`.kanban-toast`, ver templates/_design_tokens.html), reimplementado
  // aqui (não importado) porque este script pode existir SOZINHO na
  // página (usuário com `add_opportunities` mas sem `change_opportunity_
  // stage` nunca carrega kanban.js).
  // -------------------------------------------------------------------
  function showToast(message) {
    var existing = document.querySelector(".kanban-toast");
    if (existing) existing.remove();
    var toast = document.createElement("div");
    toast.className = "kanban-toast";
    toast.setAttribute("role", "alert");
    toast.textContent = message;
    document.body.appendChild(toast);
    window.setTimeout(function () {
      toast.remove();
    }, 5000);
  }

  function refreshEmptyState(dropZone) {
    var emptyMsg = dropZone.querySelector(".kanban-column-empty");
    if (emptyMsg) emptyMsg.remove();
  }

  // -------------------------------------------------------------------
  // "Sujo"? — algum campo tem valor diferente do estado inicial
  // renderizado pelo servidor (inclui a etapa pré-selecionada, que NÃO
  // conta como "sujo" sozinha). Usado só para decidir se fechar exige
  // confirmação — nunca para validação de verdade (isso é sempre o
  // backend).
  // -------------------------------------------------------------------
  function isDirty() {
    var fields = fieldsContainer.querySelectorAll("input, select, textarea");
    for (var i = 0; i < fields.length; i++) {
      var el = fields[i];
      if (el.type === "hidden") continue;
      if (el.tagName === "SELECT") {
        var defaultOption = el.querySelector("option[selected]");
        var defaultValue = defaultOption ? defaultOption.value : "";
        if (el.value !== defaultValue) return true;
      } else if (el.value && String(el.value).trim() !== "") {
        return true;
      }
    }
    return false;
  }

  function resetForm() {
    fieldsContainer.innerHTML = pristineFieldsHtml;
  }

  // -------------------------------------------------------------------
  // Foco preso dentro do drawer (Tab/Shift+Tab não escapam para o Kanban
  // ao fundo) — implementação simples (primeiro/último elemento focável
  // da vez), sem dependência nova.
  // -------------------------------------------------------------------
  function focusableElements() {
    var items = drawer.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    return Array.prototype.filter.call(items, function (el) {
      return el.offsetParent !== null;
    });
  }

  function trapFocus(event) {
    if (event.key !== "Tab") return;
    var items = focusableElements();
    if (items.length === 0) return;
    var first = items[0];
    var last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onKeydown(event) {
    if (event.key === "Escape") {
      requestClose();
      return;
    }
    trapFocus(event);
  }

  // -------------------------------------------------------------------
  // Abrir / fechar — mesmo mecanismo do drawer do menu mobile
  // (templates/base.html: alterna a classe `.hidden` do Tailwind, nunca
  // o atributo `hidden` nativo — evita por completo o conflito de
  // cascata já documentado em `.kanban-modal-backdrop[hidden]`).
  // -------------------------------------------------------------------
  function openDrawer() {
    drawer.classList.remove("hidden");
    backdrop.classList.remove("hidden");
    resetDiscardState();
    // Foco inicial no primeiro campo do formulário (`title`, id padrão
    // do Django `id_title`) — mais útil que o botão de fechar num
    // drawer cuja ação principal é preencher um formulário; cai para o
    // botão de fechar se por algum motivo o campo não existir (ex.:
    // fragmento de erro sem esse campo específico renderizado).
    var titleField = fieldsContainer.querySelector("#id_title");
    if (titleField) {
      titleField.focus();
    } else {
      closeBtn.focus();
    }
    document.addEventListener("keydown", onKeydown);
  }

  function closeDrawer() {
    drawer.classList.add("hidden");
    backdrop.classList.add("hidden");
    document.removeEventListener("keydown", onKeydown);
    resetDiscardState();
    openLink.focus();
  }

  function resetDiscardState() {
    pendingDiscardConfirm = false;
    if (discardTimer) {
      window.clearTimeout(discardTimer);
      discardTimer = null;
    }
    cancelBtn.textContent = CANCEL_DEFAULT_LABEL;
  }

  // Fechar com dados digitados exige um segundo clique/ESC, em vez de um
  // `confirm()` nativo bloqueante — aviso DISCRETO (pedido explícito:
  // "não criar confirmação irritante"), nunca para formulário vazio.
  function requestClose() {
    if (isSubmitting) return;
    if (!isDirty() || pendingDiscardConfirm) {
      resetForm();
      closeDrawer();
      return;
    }
    pendingDiscardConfirm = true;
    cancelBtn.textContent = "Clique novamente para descartar";
    discardTimer = window.setTimeout(resetDiscardState, 4000);
  }

  openLink.addEventListener("click", function (event) {
    // Progressive enhancement: com JS ativo, nunca navega — abre o
    // drawer. Sem este listener (JS indisponível/falhou ao carregar), o
    // <a href> segue normalmente para a rota tradicional de criação.
    event.preventDefault();
    openDrawer();
  });
  closeBtn.addEventListener("click", requestClose);
  cancelBtn.addEventListener("click", requestClose);
  backdrop.addEventListener("click", requestClose);

  // -------------------------------------------------------------------
  // Envio — sempre o mesmo endpoint da rota tradicional, nunca outro.
  // -------------------------------------------------------------------
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (isSubmitting) return;

    isSubmitting = true;
    submitBtn.disabled = true;
    submitBtn.textContent = "Criando...";

    var formData = new FormData(form);
    var url = form.getAttribute("action") + (filtersQuery ? "?" + filtersQuery : "");

    fetch(url, {
      method: "POST",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: formData,
      credentials: "same-origin",
    })
      .then(function (response) {
        if (response.status === 400) {
          return response.text().then(function (html) {
            return { kind: "invalid", html: html };
          });
        }
        return response.json().then(function (data) {
          return { kind: "ok", data: data };
        });
      })
      .then(function (result) {
        isSubmitting = false;
        submitBtn.disabled = false;
        submitBtn.textContent = "Criar oportunidade";

        if (result.kind === "invalid") {
          // Erro de validação: NUNCA fecha o drawer, NUNCA perde os
          // dados — o fragmento devolvido pelo backend já vem com os
          // valores reenviados (form bound) e as mensagens de erro
          // próximas a cada campo.
          fieldsContainer.innerHTML = result.html;
          var firstError = fieldsContainer.querySelector(".field-error, .alert-error");
          if (firstError) {
            firstError.scrollIntoView({ block: "nearest" });
          }
          return;
        }

        if (!result.data.ok) {
          showToast(result.data.error || "Não foi possível criar a oportunidade.");
          return;
        }

        if (result.data.matches_current_filters && board) {
          var column = board.querySelector('.kanban-column[data-stage-id="' + result.data.stage_id + '"]');
          if (column) {
            var dropZone = column.querySelector("[data-drop-zone]");
            if (dropZone) {
              refreshEmptyState(dropZone);
              dropZone.insertAdjacentHTML("afterbegin", result.data.card_html);
            }
            if (result.data.destination_stage) {
              var countEl = column.querySelector(".kanban-column-count");
              var totalEl = column.querySelector(".kanban-column-total");
              if (countEl) countEl.textContent = result.data.destination_stage.count;
              if (totalEl) totalEl.textContent = result.data.destination_stage.total_value_display;
            }
          }
        }

        showToast(result.data.message || "Oportunidade criada.");
        resetForm();
        closeDrawer();
      })
      .catch(function () {
        isSubmitting = false;
        submitBtn.disabled = false;
        submitBtn.textContent = "Criar oportunidade";
        showToast("Falha de comunicação ao criar a oportunidade — tente novamente.");
      });
  });
})();
