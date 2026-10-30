(() => {
  "use strict";
  const ICON_BASE = "https://blocksitems.com/api/2026.1.2/icon/";
  const PLACEHOLDER = "/placeholder.svg";
  const ITEM_ID = /^[a-z0-9_.-]+:[a-z0-9_.-]+(?:\/[a-z0-9_.-]+)*$/;
  const preferenceKey = "chestcount.viewer.v1";

  function iconUrl(id) {
    return typeof id === "string" && ITEM_ID.test(id) && id.length <= 512 && !id.split(":")[1].split("/").some(part => part === "." || part === "..")
      ? `${ICON_BASE}${encodeURIComponent(id)}.png?size=64&placeholder=404` : PLACEHOLDER;
  }
  function chestPath(world, chest) {
    const base = `/api/v1/worlds/${encodeURIComponent(world)}/chests`;
    return chest === undefined ? base : `${base}/${encodeURIComponent(chest)}`;
  }
  function inventorySize(chest) {
    const blocks = chest?.identity?.blocks;
    if (!Array.isArray(blocks) || ![1, 2].includes(blocks.length)) return null;
    if (blocks.some(b => !b || ![b.x, b.y, b.z].every(Number.isInteger))) return null;
    if (blocks.length === 2) {
      const [a, b] = blocks;
      if (a.y !== b.y || Math.abs(a.x - b.x) + Math.abs(a.z - b.z) !== 1) return null;
    }
    return blocks.length * 27;
  }
  function inventoryModel(chest) {
    const size = inventorySize(chest);
    const slots = Array(size || 0).fill(null);
    const warnings = [];
    if (!Array.isArray(chest?.items)) warnings.push("O servidor não disponibilizou uma lista de itens válida.");
    for (const item of Array.isArray(chest?.items) ? chest.items : []) {
      if (!item || !Number.isInteger(item.slot) || !Number.isInteger(item.count) || item.count <= 0 || typeof item.item_id !== "string") {
        warnings.push("Há registos de itens inválidos neste snapshot."); continue;
      }
      if (size === null || item.slot < 0 || item.slot >= size) {
        warnings.push("Há itens que não podem ser posicionados com segurança na identidade recebida."); continue;
      }
      if (slots[item.slot]) { warnings.push("O snapshot contém mais de um item no mesmo slot."); continue; }
      slots[item.slot] = { slot: item.slot, item_id: item.item_id, count: item.count };
    }
    return { size, slots, warnings: [...new Set(warnings)] };
  }
  function coordinates(chest) {
    const blocks = chest?.identity?.blocks;
    if (!Array.isArray(blocks) || !blocks.length) return "Coordenadas indisponíveis";
    return blocks.map(b => b && [b.x, b.y, b.z].every(Number.isInteger) ? `${b.x}, ${b.y}, ${b.z}` : "?").join(" / ");
  }
  function worldLabel(id) {
    if (id.startsWith("local:")) return `Mundo local · ${id.slice(6, 18)}…`;
    if (id.startsWith("integration-test:")) return `Teste de integração · ${id.slice(-12)}`;
    return id.length > 38 ? `${id.slice(0, 22)}…${id.slice(-10)}` : id;
  }
  function dateText(value) {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "medium" }) : "Não disponível";
  }

  function createApp(doc, options = {}) {
    const win = doc.defaultView;
    const fetcher = options.fetcher || win.fetch.bind(win);
    const intervalMs = options.intervalMs ?? 10000;
    let saved = {};
    try { saved = JSON.parse(win.localStorage.getItem(preferenceKey) || "{}"); } catch (_) { /* Storage is optional. */ }
    if (!saved || typeof saved !== "object") saved = {};
    const state = {
      world: typeof saved.world === "string" ? saved.world : "",
      chestId: typeof saved.chestId === "string" ? saved.chestId : "",
      slot: Number.isInteger(saved.slot) && saved.slot >= 0 && saved.slot < 54 ? saved.slot : null,
      worlds: [], chests: [], chest: null, lastRefresh: null, busy: false
    };
    const el = id => doc.getElementById(id);
    const events = new AbortController();
    const failedIcons = new Set();
    let timer = null, controller = null, sequence = 0, destroyed = false, started = false;
    let gridSignature = "", detailSignature = "", listSignature = "", worldSignature = "";
    el("auto-refresh").checked = saved.automatic !== false;
    el("show-deleted").checked = saved.showDeleted === true;
    function text(id, value) { el(id).textContent = value; }
    function node(tag, className, content) {
      const element = doc.createElement(tag);
      if (className) element.className = className;
      if (content !== undefined) element.textContent = String(content);
      return element;
    }
    function save() {
      try { win.localStorage.setItem(preferenceKey, JSON.stringify({ world: state.world, chestId: state.chestId, slot: state.slot, automatic: el("auto-refresh").checked, showDeleted: el("show-deleted").checked })); } catch (_) {}
    }
    function image(id) {
      const img = node("img", "item-icon");
      img.alt = id; img.draggable = false; img.loading = "lazy"; img.decoding = "async";
      img.referrerPolicy = "no-referrer";
      const url = failedIcons.has(id) ? PLACEHOLDER : iconUrl(id);
      if (url !== PLACEHOLDER) img.addEventListener("error", () => {
        failedIcons.add(id); img.src = PLACEHOLDER; img.classList.add("fallback-icon"); img.title = `Ícone indisponível: ${id}`;
      }, { once: true });
      img.src = url;
      return img;
    }
    async function json(url, signal) {
      const response = await fetcher(url, { method: "GET", cache: "no-store", headers: { Accept: "application/json" }, signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }
    function schedule() {
      win.clearTimeout(timer);
      if (!destroyed && el("auto-refresh").checked && !doc.hidden) timer = win.setTimeout(() => refresh(), intervalMs);
    }
    function connection(ok, message) {
      el("connection").className = `connection ${ok ? "online" : "offline"}`;
      text("connection", message);
    }
    function renderWorlds() {
      const signature = JSON.stringify(state.worlds.map(w => [w.id, worldLabel(w.id)]));
      if (signature !== worldSignature) {
        worldSignature = signature;
        const options = state.worlds.map(w => {
          const option = node("option", null, worldLabel(w.id)); option.value = w.id; option.title = w.id; return option;
        });
        if (!options.length) { const option = node("option", null, "Nenhum mundo sincronizado"); option.value = ""; options.push(option); }
        el("world-select").replaceChildren(...options);
      }
      el("world-select").value = state.world;
      el("world-select").disabled = !state.worlds.length;
      text("world-id", state.world || "Ainda não há mundos no servidor.");
      const world = state.worlds.find(w => w.id === state.world);
      text("world-updated", world?.updated_at ? `Mundo atualizado: ${dateText(world.updated_at)}` : "");
    }
    function renderList() {
      const active = state.chests.filter(c => !c.deleted);
      text("chest-count", String(active.length));
      const visible = state.chests.filter(c => !c.deleted || el("show-deleted").checked || c.id === state.chestId);
      const signature = JSON.stringify([state.chestId, visible.map(c => [c.id, c.name, c.deleted, c.serverRevision, coordinates(c)])]);
      if (signature !== listSignature) {
        listSignature = signature;
        const scroll = el("chest-list").scrollTop;
        const focused = doc.activeElement?.dataset?.chestId;
        const buttons = visible.map(chest => {
          const button = node("button", `chest-button${chest.id === state.chestId ? " selected" : ""}${chest.deleted ? " deleted" : ""}`);
          button.type = "button"; button.dataset.chestId = chest.id; button.setAttribute("aria-pressed", String(chest.id === state.chestId));
          const icon = node("img"); icon.src = "/chest.svg"; icon.alt = "";
          const copy = node("span", "chest-copy");
          copy.append(node("span", "list-name", chest.name || chest.id), node("span", "list-sub", chest.deleted ? "Removido · histórico" : coordinates(chest)));
          button.append(icon, copy, node("span", "list-arrow", "›"));
          return button;
        });
        el("chest-list").replaceChildren(...buttons); el("chest-list").scrollTop = scroll;
        if (focused) buttons.find(b => b.dataset.chestId === focused)?.focus({ preventScroll: true });
      }
      el("list-empty").hidden = visible.length > 0;
      text("list-empty", state.chests.length ? "Não há baús ativos. Ativa ‘Mostrar removidos’ para consultar o histórico." : "Nenhum baú sincronizado. Regista um baú no Minecraft para começar.");
    }
    function selectSlot(index) {
      state.slot = index; save(); renderSelection(); renderDetails();
    }
    function renderSelection() {
      el("inventory-grid").querySelectorAll("button").forEach(button => {
        const selected = Number(button.dataset.slot) === state.slot;
        button.classList.toggle("selected", selected); button.setAttribute("aria-pressed", String(selected));
      });
    }
    function renderDetails() {
      const model = state.chest ? inventoryModel(state.chest) : null;
      const index = state.slot;
      const item = model && index !== null ? model.slots[index] : null;
      const signature = JSON.stringify([state.chest?.id, state.chest?.name, state.chest?.syncedAt, index, item]);
      if (signature === detailSignature) return;
      detailSignature = signature;
      el("detail-preview").replaceChildren(item ? image(item.item_id) : node("span", "preview-cross", "+"));
      text("detail-kicker", item ? "ITEM SELECIONADO" : index === null ? "À TUA ESCOLHA" : "SLOT SELECIONADO");
      text("detail-name", item ? item.item_id.split(":")[1]?.replaceAll("_", " ") || item.item_id : index === null ? "Seleciona um slot" : state.chest?.syncedAt ? "Slot vazio" : "Sem dados confirmados");
      text("detail-description", item ? "Identificado pelo ID original do Minecraft." : index === null ? "Os detalhes do item aparecem aqui." : state.chest?.syncedAt ? "Não há itens neste slot do snapshot." : "Abre e fecha este baú no Minecraft para confirmar os itens.");
      text("detail-id", item?.item_id || "—"); text("detail-count", item ? String(item.count) : "—");
      text("detail-slot", index === null ? "—" : String(index)); text("detail-chest", state.chest?.name || "—");
    }
    function renderInventory() {
      const chest = state.chest;
      el("welcome").hidden = Boolean(chest); el("chest-view").hidden = !chest;
      if (!chest) {
        text("welcome-text", !state.worlds.length ? "Nenhum baú sincronizado. Regista um baú no Minecraft para começar." : state.chestId && state.busy ? "A consultar o snapshot do baú…" : "Seleciona um mundo e um baú para explorar o inventário.");
        state.slot = null; renderDetails(); return;
      }
      const model = inventoryModel(chest);
      if (state.slot !== null && (model.size === null || state.slot >= model.size)) state.slot = null;
      text("chest-name", chest.name || chest.id); text("chest-id", chest.id);
      text("dimension", chest.identity?.dimension || "Dimensão desconhecida"); text("coordinates", coordinates(chest));
      text("chest-type", model.size === 27 ? "SIMPLES · 27 SLOTS" : model.size === 54 ? "DUPLO · 54 SLOTS" : "TAMANHO DESCONHECIDO");
      const occupied = model.slots.filter(Boolean);
      text("slot-summary", model.size ? `${occupied.length} / ${model.size} slots ocupados` : "Identidade incompleta");
      const notices = [...model.warnings];
      if (chest.deleted) notices.unshift("Baú removido. Este inventário é um snapshot histórico, não um baú ativo.");
      if (chest.structureChanged) notices.push("Estrutura alterada. O inventário e as coordenadas são os últimos dados conhecidos.");
      if (!chest.syncedAt) notices.push("Inventário ainda não confirmado. Os slots vazios não comprovam que o baú esteja vazio.");
      el("chest-notice").hidden = !notices.length; text("chest-notice", notices.join(" "));
      el("unknown-size").hidden = model.size !== null; el("inventory-grid").hidden = model.size === null;
      const signature = JSON.stringify([chest.id, model.size, model.slots, Boolean(chest.syncedAt)]);
      if (signature !== gridSignature) {
        gridSignature = signature;
        const focusedSlot = doc.activeElement?.dataset?.slot;
        const buttons = model.slots.map((item, index) => {
          const button = node("button", "slot"); button.type = "button"; button.dataset.slot = String(index);
          const label = item ? `Slot ${index}: ${item.item_id}, quantidade ${item.count}` : `Slot ${index}: ${chest.syncedAt ? "vazio" : "sem leitura confirmada"}`;
          button.setAttribute("aria-label", label); button.title = label;
          button.append(node("span", "slot-index", String(index)));
          if (item) button.append(image(item.item_id), node("span", `stack-count${item.count > 999 ? " long-count" : ""}`, item.count));
          return button;
        });
        el("inventory-grid").replaceChildren(...buttons);
        if (focusedSlot !== undefined) buttons[Number(focusedSlot)]?.focus({ preventScroll: true });
      }
      text("chest-total", chest.syncedAt ? `${occupied.reduce((sum, item) => sum + item.count, 0)} itens · ${new Set(occupied.map(i => i.item_id)).size} tipos` : "Leitura ainda não confirmada");
      text("server-revision", Number.isInteger(chest.serverRevision) ? `Revisão #${chest.serverRevision}` : "Revisão indisponível");
      text("snapshot-time", chest.syncedAt ? `Última leitura do inventário: ${dateText(chest.syncedAt)}` : "Ainda sem uma leitura confirmada do inventário");
      renderSelection(); renderDetails();
    }
    function render() { renderWorlds(); renderList(); renderInventory(); }
    async function refresh() {
      if (destroyed) return;
      win.clearTimeout(timer); controller?.abort(); controller = new AbortController();
      const current = ++sequence, signal = controller.signal;
      const timeout = win.setTimeout(() => controller?.signal === signal && controller.abort(), 8000);
      state.busy = true; el("refresh").disabled = true; el("refresh").setAttribute("aria-busy", "true");
      if (state.chestId && !state.chest) renderInventory();
      let healthy = false;
      try {
        const [health, payload] = await Promise.all([json("/api/v1/health", signal), json("/api/v1/worlds", signal)]);
        if (current !== sequence || destroyed) return;
        if (health.success !== true || health.service !== "chestcount" || !Array.isArray(payload.worlds)) throw new Error("Resposta da API inválida");
        healthy = true;
        const worlds = payload.worlds.filter(w => w && typeof w.id === "string").sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
        let world = worlds.some(w => w.id === state.world) ? state.world : (worlds.find(w => !w.id.startsWith("integration-test:")) || worlds[0])?.id || "";
        let chests = [], detail = null, chestId = state.chestId;
        if (world) {
          const list = await json(chestPath(world), signal);
          if (!Array.isArray(list.chests)) throw new Error("Lista de baús inválida");
          chests = list.chests.filter(c => c && typeof c.id === "string").sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id), "pt-PT"));
          if (!chests.some(c => c.id === chestId)) chestId = chests.find(c => !c.deleted)?.id || (el("show-deleted").checked ? chests[0]?.id : "") || "";
          const selected = chests.find(c => c.id === chestId);
          if (selected) {
            detail = state.chest && state.world === world && state.chest.id === chestId && state.chest.serverRevision === selected.serverRevision && state.chest.deleted === selected.deleted ? state.chest : await json(chestPath(world, chestId), signal);
            if (!detail || detail.id !== chestId || detail.identity?.world !== world) throw new Error("O baú recebido não pertence ao mundo selecionado");
          }
        } else chestId = "";
        if (current !== sequence || destroyed) return;
        if (state.world !== world || state.chestId !== chestId) state.slot = null;
        state.worlds = worlds; state.world = world; state.chests = chests; state.chestId = chestId; state.chest = detail;
        state.lastRefresh = new Date(); el("error").hidden = true; connection(true, "Servidor ligado");
        text("last-refresh", `Última consulta às ${state.lastRefresh.toLocaleTimeString("pt-PT")}`);
        render(); save();
      } catch (error) {
        if (current !== sequence || destroyed) return;
        controller.abort(); connection(false, healthy ? "Erro de atualização" : "Servidor indisponível");
        el("error").hidden = false;
        text("error", healthy ? "Não foi possível atualizar os inventários. Os últimos dados recebidos foram mantidos; tenta atualizar novamente." : "Servidor indisponível. Confirma que o Chest Count está em execução. Os últimos dados recebidos foram mantidos.");
      } finally {
        win.clearTimeout(timeout);
        if (current === sequence && !destroyed) {
          state.busy = false; el("refresh").disabled = false; el("refresh").setAttribute("aria-busy", "false"); schedule();
        }
      }
    }
    function start() {
      if (started) return;
      started = true;
      // Delegate to stable containers so repeated polling does not retain removed slot/list nodes.
      el("chest-list").addEventListener("click", event => {
        const button = event.target.closest("button[data-chest-id]");
        if (!button || !el("chest-list").contains(button) || state.chestId === button.dataset.chestId) return;
        state.chestId = button.dataset.chestId; state.chest = null; state.slot = null; save(); render(); refresh();
      }, { signal: events.signal });
      el("inventory-grid").addEventListener("click", event => {
        const button = event.target.closest("button[data-slot]");
        if (button && el("inventory-grid").contains(button)) selectSlot(Number(button.dataset.slot));
      }, { signal: events.signal });
      el("inventory-grid").addEventListener("keydown", event => {
        const button = event.target.closest("button[data-slot]");
        const offset = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -9, ArrowDown: 9 }[event.key];
        if (!button || !offset) return;
        const target = Number(button.dataset.slot) + offset;
        if (target < 0 || target >= el("inventory-grid").children.length) return;
        event.preventDefault(); selectSlot(target); el("inventory-grid").children[target].focus();
      }, { signal: events.signal });
      el("world-select").addEventListener("change", () => { state.world = el("world-select").value; state.chestId = ""; state.chest = null; state.chests = []; state.slot = null; save(); render(); refresh(); }, { signal: events.signal });
      el("refresh").addEventListener("click", () => refresh(), { signal: events.signal });
      el("auto-refresh").addEventListener("change", () => { save(); schedule(); }, { signal: events.signal });
      el("show-deleted").addEventListener("change", () => { save(); renderList(); if (!state.chestId) refresh(); }, { signal: events.signal });
      doc.addEventListener("visibilitychange", () => { win.clearTimeout(timer); if (!doc.hidden && el("auto-refresh").checked) refresh(); }, { signal: events.signal });
      return refresh();
    }
    function destroy() { destroyed = true; ++sequence; events.abort(); controller?.abort(); win.clearTimeout(timer); }
    return { start, refresh, destroy };
  }
  window.ChestCount = Object.freeze({ iconUrl, chestPath, inventorySize, inventoryModel, coordinates, createApp });
  window.chestCountApp = createApp(document);
  window.chestCountApp.start();
})();
