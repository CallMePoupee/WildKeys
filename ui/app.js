/* WildKeys UI — polls Python; never relies on evaluate_js pushes */

const $ = (sel) => document.querySelector(sel);

const state = {
  enabled: true,
  cards: [],
  selected: null,
  dirty: false,
  revision: 0,
  statusTs: 0,
  pasteTs: 0,
  booted: false,
  saving: false,
};

const els = {
  deck: $("#deck"),
  enabledToggle: $("#enabledToggle"),
  toggleLabel: $("#toggleLabel"),
  editorTitle: $("#editorTitle"),
  editorShortcut: $("#editorShortcut"),
  editorKeyLetter: $("#editorKeyLetter"),
  labelInput: $("#labelInput"),
  saveSuccessGif: $("#saveSuccessGif"),
  linesEditor: $("#linesEditor"),
  lineGutter: $("#lineGutter"),
  linesInput: $("#linesInput"),
  lineCount: $("#lineCount"),
  saveBtn: $("#saveBtn"),
  previewBtn: $("#previewBtn"),
  toast: $("#toast"),
  previewModal: $("#previewModal"),
  previewModalText: $("#previewModalText"),
  previewModalClose: $("#previewModalClose"),
  previewModalDone: $("#previewModalDone"),
  unsavedModal: $("#unsavedModal"),
  unsavedModalClose: $("#unsavedModalClose"),
  unsavedKeepBtn: $("#unsavedKeepBtn"),
  unsavedDiscardBtn: $("#unsavedDiscardBtn"),
  errorModal: $("#errorModal"),
  errorModalClose: $("#errorModalClose"),
  errorModalOk: $("#errorModalOk"),
  errorModalLead: $("#errorModalLead"),
  errorModalTitle: $("#errorModalTitle"),
  titlebar: $("#titlebar"),
  winMin: $("#winMin"),
  winClose: $("#winClose"),
  titlebarDrag: $("#titlebarDrag"),
  loadingModal: $("#loadingModal"),
};

function api() {
  return window.pywebview?.api ?? null;
}

function apiReady() {
  const a = api();
  if (!a || typeof a !== "object") return false;
  // Prefer explicit methods; fall back to any bound API surface
  if (typeof a.boot === "function") return true;
  if (typeof a.ping === "function") return true;
  if (typeof a.get_state === "function") return true;
  try {
    return Object.keys(a).length > 0;
  } catch (_) {
    return false;
  }
}

async function call(method, ...args) {
  // Brief retry — methods can appear a tick after pywebviewready
  for (let i = 0; i < 40; i += 1) {
    const a = api();
    if (a && typeof a[method] === "function") {
      return a[method](...args);
    }
    await sleep(50);
  }
  throw new Error("Bridge not ready");
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/** Wait until pywebview has exposed the Python API (event + poll fallback). */
function waitForBridge(timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    if (apiReady()) {
      resolve();
      return;
    }

    let settled = false;
    const finish = (fn, arg) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("pywebviewready", onReady);
      clearInterval(poll);
      clearTimeout(timer);
      fn(arg);
    };

    const onReady = () => {
      // finish.js dispatches ready right after _createApi — poll a few frames
      let n = 0;
      const poke = () => {
        if (apiReady()) {
          finish(resolve);
          return;
        }
        n += 1;
        if (n < 40) setTimeout(poke, 25);
      };
      poke();
    };

    window.addEventListener("pywebviewready", onReady);

    const poll = setInterval(() => {
      if (apiReady()) finish(resolve);
    }, 40);

    const timer = setTimeout(() => {
      finish(reject, new Error("bridge-timeout"));
    }, timeoutMs);
  });
}

function lineCountFromText(text) {
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean).length;
}

function showToast(message, kind = "") {
  els.toast.hidden = false;
  els.toast.className = "toast" + (kind ? ` ${kind}` : "");
  els.toast.textContent = message;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    els.toast.hidden = true;
  }, 3200);
}

function setStatus(_text, _mode = "on") {
  // Status pill removed from UI; keep for internal no-op calls
}

function applyState(payload, { forceEditor = false } = {}) {
  if (!payload) return;

  state.enabled = !!payload.enabled;
  // Preserve any already-loaded lines when refreshing metadata-only cards
  const prevLines = {};
  for (const c of state.cards || []) {
    if (c.lines) prevLines[c.key] = c.lines;
  }
  state.cards = (payload.cards || []).map((c) => ({
    ...c,
    lines: c.lines != null ? c.lines : prevLines[c.key],
  }));
  if (payload.revision != null) state.revision = payload.revision;
  if (payload.statusTs != null) state.statusTs = payload.statusTs;

  // Optional full body for the active key (e.g. after save)
  if (payload.activeKey && payload.activeKey.key) {
    const ak = payload.activeKey;
    const idx = state.cards.findIndex((c) => c.key === ak.key);
    if (idx >= 0) {
      state.cards[idx] = { ...state.cards[idx], ...ak, lines: ak.lines || [] };
    }
  }

  if (els.enabledToggle) {
    els.enabledToggle.checked = state.enabled;
  }
  if (els.toggleLabel) {
    els.toggleLabel.textContent = state.enabled ? "Armed" : "Paused";
  }

  const mode = state.enabled ? "on" : "off";
  setStatus(
    payload.status || (state.enabled ? "Hotkeys armed" : "Hotkeys paused"),
    mode
  );

  renderDeck();

  if (state.selected) {
    const card = state.cards.find((c) => c.key === state.selected);
    if (card && (!state.dirty || forceEditor)) {
      if (card.lines != null) {
        fillEditor(card);
        state.dirty = false;
      }
    }
  }
}

function renderDeck() {
  const prevFocusKey = document.activeElement?.dataset?.key;
  const armed = state.enabled;
  els.deck.innerHTML = "";
  for (const card of state.cards) {
    const keyOn = armed && card.enabled !== false;
    const row = document.createElement("div");
    row.className =
      "deck-row" + (keyOn ? "" : " key-off") + (armed ? "" : " global-paused");
    row.dataset.key = card.key;
    row.setAttribute("role", "listitem");

    const toggleTitle = !armed
      ? "Turn Armed on to enable shortcuts"
      : keyOn
        ? "Shortcut on"
        : "Shortcut off";

    row.innerHTML = `
      <div class="key-combo" aria-label="${escapeHtml(card.shortcut)}">
        <span class="key-badge mod">Ctrl</span>
        <span class="key-badge mod">Alt</span>
        <span class="key-badge letter">${card.key.toUpperCase()}</span>
      </div>
      <button type="button" class="card${
        state.selected === card.key ? " active" : ""
      }" data-key="${card.key}">
        <div class="card-label">${escapeHtml(card.label)}</div>
      </button>
      <label class="toggle toggle-sm row-toggle${
        armed ? "" : " is-locked"
      }" title="${escapeHtml(toggleTitle)}">
        <input type="checkbox" class="key-enabled" data-key="${card.key}" ${
      keyOn ? "checked" : ""
    } ${armed ? "" : "disabled"} />
        <span class="toggle-track">
          <span class="toggle-thumb"></span>
        </span>
      </label>
    `;

    row.querySelector(".card")?.addEventListener("click", () => {
      selectKey(card.key);
    });

    const toggle = row.querySelector(".key-enabled");
    toggle?.addEventListener("change", () => {
      if (!state.enabled) {
        toggle.checked = false;
        showToast("Turn Armed on before enabling a shortcut", "error");
        return;
      }
      toggleKeyEnabled(card.key, !!toggle.checked);
    });

    els.deck.appendChild(row);

    if (prevFocusKey === card.key) {
      row.querySelector(".card")?.focus({ preventScroll: true });
    }
  }
}

async function toggleKeyEnabled(key, enabled) {
  if (enabled && !state.enabled) {
    showToast("Turn Armed on before enabling a shortcut", "error");
    renderDeck();
    return;
  }
  try {
    const next = await call("set_key_enabled", key, enabled);
    if (next && next.ok === false) {
      showToast(next.message || "Could not update shortcut", "error");
    }
    // Keep current selection/editor; just refresh deck flags
    const prevSelected = state.selected;
    const wasDirty = state.dirty;
    applyState(next);
    state.selected = prevSelected;
    state.dirty = wasDirty;
    renderDeck();
  } catch (err) {
    showToast(String(err.message || err), "error");
    await refreshFull();
  }
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

let _unsavedResolver = null;

function openUnsavedModal() {
  return new Promise((resolve) => {
    _unsavedResolver = resolve;
    if (!els.unsavedModal) {
      resolve(false);
      return;
    }
    els.unsavedModal.hidden = false;
    document.body.style.overflow = "hidden";
  });
}

function closeUnsavedModal(discard) {
  if (els.unsavedModal) els.unsavedModal.hidden = true;
  if (!els.previewModal || els.previewModal.hidden) {
    document.body.style.overflow = "";
  }
  if (_unsavedResolver) {
    const resolve = _unsavedResolver;
    _unsavedResolver = null;
    resolve(!!discard);
  }
}

async function selectKey(key) {
  if (state.dirty && state.selected && state.selected !== key) {
    const discard = await openUnsavedModal();
    if (!discard) return;
  }

  let card = state.cards.find((c) => c.key === key);
  if (!card) return;

  state.selected = key;
  state.dirty = false;
  hideSaveSuccess();
  renderDeck();

  // Lazy-load list body (keeps boot payload tiny / fast)
  if (card.lines == null) {
    try {
      const detail = await call("get_key", key);
      if (detail?.ok) {
        card = {
          ...card,
          label: detail.label || card.label,
          lines: detail.lines || [],
          count: detail.count ?? (detail.lines || []).length,
          enabled: detail.enabled !== false,
        };
        const idx = state.cards.findIndex((c) => c.key === key);
        if (idx >= 0) state.cards[idx] = card;
      } else {
        card = { ...card, lines: [] };
      }
    } catch (_) {
      card = { ...card, lines: [] };
    }
  }

  // Selection may have changed while loading
  if (state.selected !== key) return;
  fillEditor(card);
  renderDeck();
}

function fillEditor(card) {
  els.editorTitle.textContent = card.label;
  if (els.editorShortcut) {
    els.editorShortcut.dataset.key = card.key;
    els.editorShortcut.setAttribute("aria-label", card.shortcut);
  }
  if (els.editorKeyLetter) {
    els.editorKeyLetter.textContent = card.key.toUpperCase();
  }

  els.labelInput.disabled = false;
  els.linesInput.disabled = false;
  setLinesEditorDisabled(false);
  els.saveBtn.disabled = false;
  els.previewBtn.disabled = false;

  els.labelInput.value = card.label;
  els.linesInput.value = (card.lines || []).join("\n");
  els.lineCount.textContent = String(card.count);
  updateLineGutter();
}

function rawLineCount(text) {
  // Visual rows in the textarea (empty trailing line still counts as a row)
  if (text === "") return 1;
  return text.split(/\r?\n/).length;
}

function updateLineGutter() {
  if (!els.lineGutter || !els.linesInput) return;
  const n = rawLineCount(els.linesInput.value);
  const digits = String(n).length;
  els.lineGutter.style.setProperty("--digits", String(digits));
  let out = "";
  for (let i = 1; i <= n; i += 1) {
    out += (i > 1 ? "\n" : "") + i;
  }
  els.lineGutter.textContent = out;
  els.lineGutter.scrollTop = els.linesInput.scrollTop;
}

function syncGutterScroll() {
  if (!els.lineGutter || !els.linesInput) return;
  els.lineGutter.scrollTop = els.linesInput.scrollTop;
}

function setLinesEditorDisabled(disabled) {
  if (!els.linesEditor) return;
  els.linesEditor.classList.toggle("is-disabled", !!disabled);
}

function markDirty() {
  if (!state.selected) return;
  state.dirty = true;
  els.lineCount.textContent = String(lineCountFromText(els.linesInput.value));
  els.editorTitle.textContent = els.labelInput.value.trim() || "Untitled";
  updateLineGutter();
}

function hideSaveSuccess() {
  clearTimeout(showSaveSuccess._t);
  showSaveSuccess._t = null;
  if (els.saveSuccessGif) els.saveSuccessGif.hidden = true;
}

function syncSuccessGifScrollbarInsets() {
  const ta = els.linesInput;
  const gif = els.saveSuccessGif;
  if (!ta || !gif) return;
  // Detect real overflow scrollbars on the lines field
  const bar = 14; // matches CSS scrollbar width
  const hasV = ta.scrollHeight > ta.clientHeight + 1;
  const hasH = ta.scrollWidth > ta.clientWidth + 1;
  gif.style.setProperty("--sb-right", hasV ? `${bar}px` : "0px");
  gif.style.setProperty("--sb-bottom", hasH ? `${bar}px` : "0px");
}

function showSaveSuccess() {
  const gif = els.saveSuccessGif;
  if (!gif) return;
  syncSuccessGifScrollbarInsets();
  // Restart GIF animation by reloading src
  const src = gif.getAttribute("src") || "success.gif";
  gif.hidden = false;
  gif.src = "";
  gif.src = src + (src.includes("?") ? "&" : "?") + "t=" + Date.now();
  clearTimeout(showSaveSuccess._t);
  showSaveSuccess._t = setTimeout(() => {
    hideSaveSuccess();
  }, 5500);
}

function openErrorModal(title, message) {
  if (!els.errorModal) return;
  if (els.errorModalTitle) els.errorModalTitle.textContent = title || "Error";
  if (els.errorModalLead) els.errorModalLead.textContent = message || "Something went wrong.";
  els.errorModal.hidden = false;
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => {
    els.errorModalOk?.focus();
  });
}

function closeErrorModal() {
  if (!els.errorModal) return;
  els.errorModal.hidden = true;
  document.body.style.overflow = "";
}

async function saveList() {
  if (!state.selected || state.saving) return;
  const title = (els.labelInput?.value || "").trim();
  if (!title) {
    openErrorModal("Cannot save", "Please enter a list name before saving.");
    // After dismiss, put focus back on the name field
    const focusName = () => {
      els.labelInput?.focus();
      els.errorModalOk?.removeEventListener("click", focusName);
      els.errorModalClose?.removeEventListener("click", focusName);
    };
    els.errorModalOk?.addEventListener("click", focusName, { once: true });
    els.errorModalClose?.addEventListener("click", focusName, { once: true });
    return;
  }
  state.saving = true;
  els.saveBtn?.classList.add("is-saving");
  try {
    const next = await call(
      "save_key",
      state.selected,
      title,
      els.linesInput.value
    );
    if (next && next.ok === false) {
      openErrorModal("Cannot save", next.message || "Could not save this list.");
      return;
    }
    state.dirty = false;
    applyState(next, { forceEditor: true });
    showSaveSuccess();
  } catch (err) {
    openErrorModal("Cannot save", String(err.message || err));
  } finally {
    // Let the 300ms mute-in settle, then animate label back over 300ms
    await new Promise((r) => setTimeout(r, 300));
    els.saveBtn?.classList.remove("is-saving");
    state.saving = false;
  }
}

function openPreviewModal() {
  if (!els.previewModal) return;
  els.previewModal.hidden = false;
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => {
    const el = els.previewModalText;
    if (el) {
      el.focus();
      const len = el.value.length;
      try {
        el.setSelectionRange(len, len);
      } catch (_) {
        /* ignore */
      }
    }
  });
}

function closePreviewModal() {
  if (!els.previewModal) return;
  els.previewModal.hidden = true;
  document.body.style.overflow = "";
}

async function previewPick() {
  if (!state.selected) return;
  openPreviewModal();
}

async function toggleEnabled() {
  try {
    const prevSelected = state.selected;
    const wasDirty = state.dirty;
    const next = await call("set_enabled", els.enabledToggle.checked);
    applyState(next);
    // Keep editor selection; deck toggles refresh from server state
    if (prevSelected) state.selected = prevSelected;
    state.dirty = wasDirty;
    renderDeck();
  } catch (err) {
    showToast(String(err.message || err), "error");
    els.enabledToggle.checked = !els.enabledToggle.checked;
  }
}

function isTitlebarChrome(target) {
  return !!target?.closest?.(
    ".win-controls, .win-btn, .toggle, button, label, input, a"
  );
}

function wireWindowControls() {
  els.winMin?.addEventListener("click", () => {
    call("window_minimize").catch(() => {});
  });
  els.winClose?.addEventListener("click", () => {
    call("window_close").catch(() => {});
  });

  // Custom drag: whole title bar except controls (reliable on Windows WebView2)
  let dragging = false;
  let originX = 0;
  let originY = 0;
  let startWinX = 0;
  let startWinY = 0;
  let moveQueued = false;
  let pendingX = 0;
  let pendingY = 0;

  async function onTitlebarPointerDown(e) {
    if (e.button !== 0) return;
    if (isTitlebarChrome(e.target)) return;
    try {
      const pos = await call("window_drag_start");
      dragging = true;
      originX = e.screenX;
      originY = e.screenY;
      startWinX = Number(pos?.x) || 0;
      startWinY = Number(pos?.y) || 0;
      els.titlebar?.classList.add("is-dragging");
      try {
        e.currentTarget.setPointerCapture?.(e.pointerId);
      } catch (_) {
        /* ignore */
      }
    } catch (_) {
      dragging = false;
    }
  }

  function flushDragMove() {
    moveQueued = false;
    if (!dragging) return;
    call("window_drag_move", pendingX, pendingY).catch(() => {});
  }

  function onTitlebarPointerMove(e) {
    if (!dragging) return;
    pendingX = startWinX + (e.screenX - originX);
    pendingY = startWinY + (e.screenY - originY);
    if (!moveQueued) {
      moveQueued = true;
      requestAnimationFrame(flushDragMove);
    }
  }

  function onTitlebarPointerUp(e) {
    if (!dragging) return;
    dragging = false;
    els.titlebar?.classList.remove("is-dragging");
    try {
      e.currentTarget.releasePointerCapture?.(e.pointerId);
    } catch (_) {
      /* ignore */
    }
  }

  const bar = els.titlebar;
  if (bar) {
    bar.addEventListener("pointerdown", onTitlebarPointerDown);
    bar.addEventListener("pointermove", onTitlebarPointerMove);
    bar.addEventListener("pointerup", onTitlebarPointerUp);
    bar.addEventListener("pointercancel", onTitlebarPointerUp);
    bar.addEventListener("lostpointercapture", onTitlebarPointerUp);
  }
}

function wire() {
  wireWindowControls();
  els.enabledToggle.addEventListener("change", toggleEnabled);
  els.labelInput.addEventListener("input", markDirty);
  els.linesInput.addEventListener("input", markDirty);
  els.linesInput.addEventListener("scroll", syncGutterScroll);
  els.linesInput.addEventListener("scroll", () => {
    if (els.saveSuccessGif && !els.saveSuccessGif.hidden) {
      syncSuccessGifScrollbarInsets();
    }
  });
  window.addEventListener("resize", () => {
    if (els.saveSuccessGif && !els.saveSuccessGif.hidden) {
      syncSuccessGifScrollbarInsets();
    }
  });
  els.saveBtn.addEventListener("click", saveList);
  els.previewBtn.addEventListener("click", previewPick);

  els.previewModalClose?.addEventListener("click", closePreviewModal);
  els.previewModalDone?.addEventListener("click", closePreviewModal);
  els.previewModal?.addEventListener("click", (e) => {
    if (e.target?.dataset?.closeModal) closePreviewModal();
  });

  els.unsavedKeepBtn?.addEventListener("click", () => closeUnsavedModal(false));
  els.unsavedModalClose?.addEventListener("click", () => closeUnsavedModal(false));
  els.unsavedDiscardBtn?.addEventListener("click", () => closeUnsavedModal(true));
  els.unsavedModal?.addEventListener("click", (e) => {
    if (e.target?.dataset?.closeUnsaved === "cancel") closeUnsavedModal(false);
  });

  els.errorModalOk?.addEventListener("click", closeErrorModal);
  els.errorModalClose?.addEventListener("click", closeErrorModal);
  els.errorModal?.addEventListener("click", (e) => {
    if (e.target?.dataset?.closeError) closeErrorModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (els.errorModal && !els.errorModal.hidden) {
      closeErrorModal();
      return;
    }
    if (els.unsavedModal && !els.unsavedModal.hidden) {
      closeUnsavedModal(false);
      return;
    }
    if (els.previewModal && !els.previewModal.hidden) {
      closePreviewModal();
    }
  });

  const saveOnChord = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      saveList();
    }
  };
  els.linesInput.addEventListener("keydown", saveOnChord);
  els.labelInput.addEventListener("keydown", saveOnChord);
}

async function refreshFull() {
  const s = await call("get_state");
  applyState(s);
  if (!state.selected && s.cards?.length) {
    await selectKey(s.cards[0].key);
  } else if (state.selected) {
    // Refresh active list body if metadata changed
    const card = state.cards.find((c) => c.key === state.selected);
    if (card && card.lines == null && !state.dirty) {
      await selectKey(state.selected);
    }
  }
}

function insertTextAtCaret(text) {
  const el = document.activeElement;
  if (!el) return false;
  const tag = (el.tagName || "").toLowerCase();
  if (tag !== "textarea" && tag !== "input") return false;
  if (el.disabled || el.readOnly) return false;

  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? start;
  const value = el.value ?? "";
  el.value = value.slice(0, start) + text + value.slice(end);
  const pos = start + text.length;
  try {
    el.setSelectionRange(pos, pos);
  } catch (_) {
    /* some inputs don't support selection */
  }
  el.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
}

function isEditableTarget(el) {
  if (!el) return false;
  const tag = (el.tagName || "").toLowerCase();
  if (tag !== "textarea" && tag !== "input") return false;
  if (el.disabled || el.readOnly) return false;
  return true;
}

async function tick() {
  if (!apiReady()) return;
  try {
    if (!state.booted) {
      const s = await call("boot");
      state.booted = true;
      applyState(s);
      if (!state.selected && s.cards?.length) await selectKey(s.cards[0].key);
      return;
    }

    const p = await call("poll");
    if (!p) return;

    if (p.statusTs && p.statusTs !== state.statusTs) {
      state.statusTs = p.statusTs;
    }

    // Single in-app paste path (worker publishes paste only when WildKeys is focused)
    if (p.pasteTs && p.pasteTs > state.pasteTs && p.paste) {
      const prevTs = state.pasteTs;
      state.pasteTs = p.pasteTs;
      // Debounce: ignore a second worker/event within 400ms
      if (p.pasteTs - prevTs < 0.4 && prevTs > 0) {
        /* skip duplicate */
      } else if (isEditableTarget(document.activeElement)) {
        insertTextAtCaret(String(p.paste));
      }
    }

    els.enabledToggle.checked = !!p.enabled;
    els.toggleLabel.textContent = p.enabled ? "Armed" : "Paused";
    state.enabled = !!p.enabled;

    // Only reload cards when the lists file changed
    if (p.revision && p.revision !== state.revision && !state.dirty) {
      await refreshFull();
    }
  } catch (_) {
    /* ignore transient bridge blips */
  }
}

function hideLoadingModal() {
  if (els.loadingModal) {
    els.loadingModal.hidden = true;
  }
  document.body.style.overflow = "";
}

function listsContentReady() {
  // Shortcut rows rendered and at least one list opened in the editor
  const deckReady = !!els.deck && els.deck.children.length > 0 && state.cards.length > 0;
  const editorReady =
    !!state.selected &&
    !!els.labelInput &&
    !els.labelInput.disabled &&
    !!els.linesInput &&
    !els.linesInput.disabled;
  return deckReady && editorReady;
}

async function waitForPaint() {
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
}

async function loadInitialState() {
  let lastErr = null;
  // Prefer ping then boot — surfaces a clearer failure if API is half-bound
  for (let i = 0; i < 50; i += 1) {
    try {
      if (typeof api()?.ping === "function") {
        await call("ping");
      }
      const s = await call("boot");
      if (s && Array.isArray(s.cards)) return s;
      lastErr = new Error("boot returned no cards");
    } catch (err) {
      lastErr = err;
    }
    await sleep(80);
  }
  throw lastErr || new Error("boot failed");
}

async function bootUi() {
  // Loading modal stays up until lists are loaded and visible
  document.body.style.overflow = "hidden";
  wire();
  updateLineGutter();
  setLinesEditorDisabled(true);

  try {
    await waitForBridge(60000);

    const s = await loadInitialState();
    state.booted = true;
    applyState(s);
    renderDeck();

    if (s.cards?.length) {
      await selectKey(s.cards[0].key);
    }

    let readyTries = 0;
    while (!listsContentReady() && readyTries < 20) {
      if (state.cards.length && els.deck && els.deck.children.length === 0) {
        renderDeck();
      }
      if (!state.cards.length) break;
      await sleep(25);
      readyTries += 1;
    }

    await waitForPaint();
    setInterval(tick, 200);
    hideLoadingModal();
  } catch (err) {
    hideLoadingModal();
    const msg = String(err?.message || err || "");
    if (msg.includes("bridge-timeout") || msg.includes("Bridge not ready")) {
      showToast(
        "Could not connect the app bridge. Quit WildKeys from the tray, then start it with Start WildKeys.bat.",
        "error"
      );
    } else {
      showToast(`Startup error: ${msg}`, "error");
    }
  }
}

document.addEventListener("DOMContentLoaded", bootUi);
// If the bridge becomes ready after a failed boot path, pywebviewready is still handled inside waitForBridge.
