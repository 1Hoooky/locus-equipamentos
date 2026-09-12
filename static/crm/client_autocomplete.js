/**
 * Autocomplete pesquisável do campo "Cliente" (CORRIGIR DEFINITIVAMENTE
 * O CAMPO CLIENTE — AUTOCOMPLETE PESQUISÁVEL A PARTIR DE 3 CARACTERES,
 * 12/09/2026).
 *
 * Substitui o `<select>` nativo (que carregava TODOS os clientes ativos
 * de uma vez) por uma busca sob demanda no backend — nunca mais que
 * ~20 resultados por requisição (ver `apps.crm.views.
 * OpportunityClientAutocompleteView`), nunca a listagem completa.
 * Continua rápido com 700, 2.000 ou 10.000 clientes porque a página
 * nunca recebe a lista inteira.
 *
 * Delegação de eventos em `document` (mesmo padrão já usado em
 * `static/crm/kanban.js` para os cards, que também são inseridos
 * dinamicamente) — de propósito: o widget aparece dentro do fragmento
 * do drawer de criação rápida (`_opportunity_quick_create_fields.html`),
 * que `static/crm/opportunity_quick_create.js` substitui inteiro via
 * `innerHTML` a cada erro de validação/reset — um listener preso a um
 * elemento específico morreria a cada troca; delegado em `document`
 * continua funcionando sem precisar re-inicializar nada depois de cada
 * substituição.
 *
 * Contrato com o backend: o `<input>` de texto visível NUNCA é enviado
 * no POST (sem `name`) — só decide QUAIS opções aparecem no dropdown.
 * O `<input type="hidden">` (com o `name` real do campo) é o único
 * valor que o Django recebe, e só é preenchido por uma seleção real no
 * dropdown — nunca por texto digitado à mão. Editar o texto depois de
 * selecionar limpa o campo oculto imediatamente (a seleção anterior
 * deixa de valer, exatamente como pedido: "ALTEROU O TEXTO = INVALIDA A
 * SELEÇÃO").
 */
(function () {
  "use strict";

  var MIN_QUERY_LENGTH = 3;
  var DEBOUNCE_MS = 275;

  // Estado por instância do widget (timer de debounce, controller do
  // fetch em andamento, índice do item ativo) — `WeakMap` em vez de
  // propriedade solta no elemento: some sozinho se o DOM for substituído
  // (troca de innerHTML do drawer), nunca vaza estado de uma instância
  // antiga para a próxima.
  var state = new WeakMap();

  function getState(wrapper) {
    var s = state.get(wrapper);
    if (!s) {
      s = { timer: null, controller: null, activeIndex: -1, requestId: 0 };
      state.set(wrapper, s);
    }
    return s;
  }

  function wrapperOf(el) {
    return el.closest("[data-client-autocomplete]");
  }

  function elements(wrapper) {
    return {
      input: wrapper.querySelector("[data-client-autocomplete-input]"),
      hidden: wrapper.querySelector("[data-client-autocomplete-hidden]"),
      dropdown: wrapper.querySelector("[data-client-autocomplete-dropdown]"),
    };
  }

  function openDropdown(wrapper) {
    var els = elements(wrapper);
    if (!els.dropdown || !els.input) return;
    els.dropdown.hidden = false;
    els.input.setAttribute("aria-expanded", "true");
  }

  function closeDropdown(wrapper) {
    var els = elements(wrapper);
    if (!els.dropdown || !els.input) return;
    els.dropdown.hidden = true;
    els.input.setAttribute("aria-expanded", "false");
    getState(wrapper).activeIndex = -1;
  }

  function renderStatus(wrapper, text) {
    var els = elements(wrapper);
    if (!els.dropdown) return;
    els.dropdown.innerHTML = "";
    var status = document.createElement("p");
    status.className = "client-autocomplete-status";
    status.textContent = text;
    els.dropdown.appendChild(status);
    getState(wrapper).activeIndex = -1;
  }

  function renderResults(wrapper, results) {
    var els = elements(wrapper);
    if (!els.dropdown) return;
    els.dropdown.innerHTML = "";
    getState(wrapper).activeIndex = -1;

    if (!results.length) {
      renderStatus(wrapper, "Nenhum cliente encontrado.");
      return;
    }

    results.forEach(function (result, index) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "client-autocomplete-item";
      item.setAttribute("role", "option");
      item.setAttribute("data-client-autocomplete-item", "");
      item.setAttribute("data-client-id", result.id);
      item.setAttribute("data-client-name", result.name);
      item.setAttribute("aria-selected", "false");
      item.setAttribute("id", (els.input.id || "client") + "-option-" + index);
      item.textContent = result.name;
      els.dropdown.appendChild(item);
    });
  }

  function setActiveIndex(wrapper, index) {
    var els = elements(wrapper);
    var items = els.dropdown ? els.dropdown.querySelectorAll("[data-client-autocomplete-item]") : [];
    if (!items.length) return;

    var s = getState(wrapper);
    var next = ((index % items.length) + items.length) % items.length; // wrap nos dois sentidos
    s.activeIndex = next;

    items.forEach(function (item, i) {
      item.setAttribute("aria-selected", i === next ? "true" : "false");
    });
    items[next].scrollIntoView({ block: "nearest" });
    if (els.input) els.input.setAttribute("aria-activedescendant", items[next].id);
  }

  function selectClient(wrapper, id, name) {
    var els = elements(wrapper);
    if (!els.input || !els.hidden) return;
    els.input.value = name;
    els.hidden.value = id;
    closeDropdown(wrapper);
  }

  function clearSelection(wrapper) {
    var els = elements(wrapper);
    if (els.hidden) els.hidden.value = "";
  }

  function abortPending(wrapper) {
    var s = getState(wrapper);
    if (s.timer) {
      clearTimeout(s.timer);
      s.timer = null;
    }
    if (s.controller) {
      s.controller.abort();
      s.controller = null;
    }
  }

  function search(wrapper, query) {
    var els = elements(wrapper);
    var s = getState(wrapper);
    var url = wrapper.getAttribute("data-client-autocomplete-url");
    if (!url) return;

    s.requestId += 1;
    var requestId = s.requestId;

    var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    s.controller = controller;

    fetch(url + "?q=" + encodeURIComponent(query), {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      signal: controller ? controller.signal : undefined,
    })
      .then(function (response) {
        if (!response.ok) throw new Error("bad status");
        return response.json();
      })
      .then(function (data) {
        // Resposta de uma busca já superada por uma mais recente
        // (usuário continuou digitando) — descartada silenciosamente.
        if (requestId !== s.requestId) return;
        renderResults(wrapper, data.results || []);
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") return;
        if (requestId !== s.requestId) return;
        renderStatus(wrapper, "Não foi possível buscar clientes agora.");
      });
  }

  // ---------------------------------------------------------------------
  // Digitação — regra dos 3 caracteres + debounce + invalidação da
  // seleção anterior.
  // ---------------------------------------------------------------------
  document.addEventListener("input", function (event) {
    var input = event.target.closest("[data-client-autocomplete-input]");
    if (!input) return;
    var wrapper = wrapperOf(input);
    if (!wrapper) return;

    // Qualquer digitação real invalida a seleção anterior — o campo
    // oculto só volta a ter um valor quando o usuário escolher um
    // resultado de verdade no dropdown.
    clearSelection(wrapper);

    abortPending(wrapper);
    var query = input.value.trim();

    if (query.length < MIN_QUERY_LENGTH) {
      closeDropdown(wrapper);
      return;
    }

    var s = getState(wrapper);
    s.timer = setTimeout(function () {
      renderStatus(wrapper, "Buscando clientes...");
      openDropdown(wrapper);
      search(wrapper, query);
    }, DEBOUNCE_MS);
  });

  // ---------------------------------------------------------------------
  // Clique num resultado.
  // ---------------------------------------------------------------------
  document.addEventListener("click", function (event) {
    var item = event.target.closest("[data-client-autocomplete-item]");
    if (item) {
      var wrapper = wrapperOf(item);
      if (wrapper) {
        selectClient(wrapper, item.getAttribute("data-client-id"), item.getAttribute("data-client-name"));
      }
      return;
    }

    // Clique fora de qualquer autocomplete — fecha todos os dropdowns
    // abertos (mesmo padrão do menu "⋯"/`data-action-menu`).
    document.querySelectorAll("[data-client-autocomplete]").forEach(function (wrapper) {
      if (!wrapper.contains(event.target)) closeDropdown(wrapper);
    });
  });

  // ---------------------------------------------------------------------
  // Teclado — seta para baixo/cima navega, Enter seleciona, Esc fecha.
  // ---------------------------------------------------------------------
  document.addEventListener("keydown", function (event) {
    var input = event.target.closest("[data-client-autocomplete-input]");
    if (!input) return;
    var wrapper = wrapperOf(input);
    if (!wrapper) return;

    var els = elements(wrapper);
    var isOpen = els.dropdown && !els.dropdown.hidden;
    var s = getState(wrapper);

    if (event.key === "ArrowDown") {
      if (!isOpen) return;
      event.preventDefault();
      setActiveIndex(wrapper, s.activeIndex + 1);
    } else if (event.key === "ArrowUp") {
      if (!isOpen) return;
      event.preventDefault();
      setActiveIndex(wrapper, s.activeIndex - 1);
    } else if (event.key === "Enter") {
      if (!isOpen) return;
      var items = els.dropdown.querySelectorAll("[data-client-autocomplete-item]");
      if (s.activeIndex >= 0 && items[s.activeIndex]) {
        // Impede o Enter de submeter o formulário inteiro (Nova
        // oportunidade) quando o objetivo era só confirmar o cliente
        // realçado na lista.
        event.preventDefault();
        var chosen = items[s.activeIndex];
        selectClient(wrapper, chosen.getAttribute("data-client-id"), chosen.getAttribute("data-client-name"));
      }
    } else if (event.key === "Escape") {
      if (!isOpen) return;
      // Só fecha o dropdown de resultados — não deixa o Esc "vazar"
      // para um handler global do drawer (ex.: fechar o drawer inteiro).
      event.stopPropagation();
      closeDropdown(wrapper);
    }
  });
})();
