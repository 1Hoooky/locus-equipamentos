/**
 * Autocomplete pesquisável do campo "Equipamento" (RODADA 3 DE
 * REFINAMENTOS DO HUB DA OPORTUNIDADE, 14/09/2026, seção 60-68 — aba
 * Equipamentos, "Vincular equipamento").
 *
 * MESMO padrão/contrato de `static/crm/client_autocomplete.js` (ver a
 * docstring daquele arquivo para o raciocínio completo) — arquivo próprio
 * em vez de generalizar o widget de Cliente para não arriscar nenhuma
 * regressão numa tela já testada e em produção fora do escopo desta
 * rodada ("corrigir e melhorar pontos específicos... sem reestruturar o
 * CRM inteiro"); reaproveita, sim, o MESMO CSS genérico
 * `.client-autocomplete-*` (`templates/_design_tokens.html` já documenta
 * esse bloco como feito de propósito para reaproveitamento futuro em
 * outro campo de busca-e-seleção).
 *
 * Busca no backend (`apps.crm.views.OpportunityEquipmentSearchView`),
 * nunca a listagem completa de patrimônio. Cada resultado mostra
 * Patrimônio (destaque) + Modelo/Localização atual (linha secundária) —
 * diferente do widget de Cliente (só um nome), por isso o HTML de cada
 * item é montado com dois elementos em vez de um `textContent` só.
 *
 * Contrato com o backend: o `<input>` de texto visível NUNCA é enviado
 * no POST (sem `name`); o `<input type="hidden">` é o único valor que o
 * Django recebe, preenchido só por uma seleção real no dropdown.
 */
(function () {
  "use strict";

  var MIN_QUERY_LENGTH = 0; // busca vazia já lista os primeiros disponíveis — igual à ideia de "navegar pelo estoque"
  var DEBOUNCE_MS = 275;

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
    return el.closest("[data-equipment-autocomplete]");
  }

  function elements(wrapper) {
    return {
      input: wrapper.querySelector("[data-equipment-autocomplete-input]"),
      hidden: wrapper.querySelector("[data-equipment-autocomplete-hidden]"),
      dropdown: wrapper.querySelector("[data-equipment-autocomplete-dropdown]"),
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
      renderStatus(wrapper, "Nenhum equipamento disponível encontrado.");
      return;
    }

    results.forEach(function (result, index) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "client-autocomplete-item";
      item.setAttribute("role", "option");
      item.setAttribute("data-equipment-autocomplete-item", "");
      item.setAttribute("data-equipment-id", result.id);
      item.setAttribute(
        "data-equipment-display",
        result.patrimonio + " — " + result.model
      );
      item.setAttribute("aria-selected", "false");
      item.setAttribute("id", (els.input.id || "equipment") + "-option-" + index);

      var main = document.createElement("span");
      main.className = "font-medium";
      main.textContent = result.patrimonio + " — " + result.model;
      var secondary = document.createElement("span");
      secondary.className = "block text-xs text-gray-500";
      secondary.textContent = "Localização atual: " + result.location;

      item.appendChild(main);
      item.appendChild(secondary);
      els.dropdown.appendChild(item);
    });
  }

  function setActiveIndex(wrapper, index) {
    var els = elements(wrapper);
    var items = els.dropdown ? els.dropdown.querySelectorAll("[data-equipment-autocomplete-item]") : [];
    if (!items.length) return;

    var s = getState(wrapper);
    var next = ((index % items.length) + items.length) % items.length;
    s.activeIndex = next;

    items.forEach(function (item, i) {
      item.setAttribute("aria-selected", i === next ? "true" : "false");
    });
    items[next].scrollIntoView({ block: "nearest" });
    if (els.input) els.input.setAttribute("aria-activedescendant", items[next].id);
  }

  function selectEquipment(wrapper, id, display) {
    var els = elements(wrapper);
    if (!els.input || !els.hidden) return;
    els.input.value = display;
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
    var s = getState(wrapper);
    var url = wrapper.getAttribute("data-equipment-autocomplete-url");
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
        if (requestId !== s.requestId) return;
        renderResults(wrapper, data.results || []);
      })
      .catch(function (error) {
        if (error && error.name === "AbortError") return;
        if (requestId !== s.requestId) return;
        renderStatus(wrapper, "Não foi possível buscar equipamentos agora.");
      });
  }

  // ---------------------------------------------------------------------
  // Digitação — debounce + invalidação da seleção anterior. Sem exigência
  // de tamanho mínimo (MIN_QUERY_LENGTH = 0): focar o campo já dispara uma
  // busca vazia, mostrando os primeiros patrimônios disponíveis — útil
  // para "navegar pelo estoque" sem precisar saber o número de antemão.
  // ---------------------------------------------------------------------
  document.addEventListener("focusin", function (event) {
    var input = event.target.closest("[data-equipment-autocomplete-input]");
    if (!input) return;
    var wrapper = wrapperOf(input);
    if (!wrapper) return;
    if (input.value.trim().length > 0) return; // já tem texto — não sobrescreve o dropdown à toa

    renderStatus(wrapper, "Buscando equipamentos...");
    openDropdown(wrapper);
    search(wrapper, "");
  });

  document.addEventListener("input", function (event) {
    var input = event.target.closest("[data-equipment-autocomplete-input]");
    if (!input) return;
    var wrapper = wrapperOf(input);
    if (!wrapper) return;

    clearSelection(wrapper);
    abortPending(wrapper);
    var query = input.value.trim();

    if (query.length < MIN_QUERY_LENGTH) {
      closeDropdown(wrapper);
      return;
    }

    var s = getState(wrapper);
    s.timer = setTimeout(function () {
      renderStatus(wrapper, "Buscando equipamentos...");
      openDropdown(wrapper);
      search(wrapper, query);
    }, DEBOUNCE_MS);
  });

  // ---------------------------------------------------------------------
  // Clique num resultado.
  // ---------------------------------------------------------------------
  document.addEventListener("click", function (event) {
    var item = event.target.closest("[data-equipment-autocomplete-item]");
    if (item) {
      var wrapper = wrapperOf(item);
      if (wrapper) {
        selectEquipment(wrapper, item.getAttribute("data-equipment-id"), item.getAttribute("data-equipment-display"));
      }
      return;
    }

    document.querySelectorAll("[data-equipment-autocomplete]").forEach(function (wrapper) {
      if (!wrapper.contains(event.target)) closeDropdown(wrapper);
    });
  });

  // ---------------------------------------------------------------------
  // Teclado — seta para baixo/cima navega, Enter seleciona, Esc fecha.
  // ---------------------------------------------------------------------
  document.addEventListener("keydown", function (event) {
    var input = event.target.closest("[data-equipment-autocomplete-input]");
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
      var items = els.dropdown.querySelectorAll("[data-equipment-autocomplete-item]");
      if (s.activeIndex >= 0 && items[s.activeIndex]) {
        event.preventDefault();
        var chosen = items[s.activeIndex];
        selectEquipment(wrapper, chosen.getAttribute("data-equipment-id"), chosen.getAttribute("data-equipment-display"));
      }
    } else if (event.key === "Escape") {
      if (!isOpen) return;
      event.stopPropagation();
      closeDropdown(wrapper);
    }
  });
})();
