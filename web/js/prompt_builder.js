// Three levels up, not two: WEB_DIRECTORY is "./web" and these live in
// web/js/, so they are served from /extensions/ComfyUI-MiseEnPlace/js/ .
// "../../scripts/app.js" resolves to /extensions/scripts/app.js, 404s, and
// silently stops the whole module - and therefore the extension - loading.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE_NAME = "PromptBuilder";
// The multiline widget that doubles as the JSON input socket.
const SOURCE_WIDGET = "prompt_json";
const MIN_VIEW_HEIGHT = 260;
const VIEWER_FONT_SIZE = 14;

// The prompt text is built here rather than taken from the node's output, so
// the panel can show any version in the history - including ones this browser
// never saw execute. Kept deliberately in step with _prompt_schema.render().
function renderPromptText(sections) {
    return (sections ?? [])
        .filter((s) => s?.content)
        .map((s) => `**${s.name}**: ${String(s.content).trim()}`)
        .join("\n\n");
}

function formatTime(epochSeconds) {
    if (!epochSeconds) return "";
    return new Date(epochSeconds * 1000).toLocaleTimeString();
}

// The id the Python side derives when the prompt_id widget is left blank
// (PromptBuilder._resolve_prompt_id).
function resolvePromptId(node) {
    const explicit = node.widgets?.find((w) => w.name === "prompt_id")?.value;
    const trimmed = typeof explicit === "string" ? explicit.trim() : "";
    return trimmed || `__node_${node.id}`;
}

let stylesInjected = false;
function ensureStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    const style = document.createElement("style");
    style.textContent = `
        /* Tokens derived from ComfyUI's --fg-color/--bg-color, which :root sets
           for the light theme and .dark-theme flips, so this reads correctly
           under both. The plain value above each color-mix() is the fallback
           for browsers that cannot parse it. */
        .zd-pb {
            --mep-pb-font: ${VIEWER_FONT_SIZE}px;
            --mep-fg: var(--fg-color, #e6e6e6);
            --mep-bg: var(--bg-color, #202020);
            --mep-accent: #2563eb;
            --mep-warn: #d97706;

            --mep-text: var(--mep-fg);
            --mep-text-muted: #808080;
            --mep-text-muted: color-mix(in srgb, var(--mep-fg) 62%, var(--mep-bg));
            --mep-panel: rgba(127, 127, 127, 0.1);
            --mep-panel: color-mix(in srgb, var(--mep-fg) 5%, var(--mep-bg));
            --mep-raised: rgba(127, 127, 127, 0.18);
            --mep-raised: color-mix(in srgb, var(--mep-fg) 11%, var(--mep-bg));
            --mep-sunken: rgba(127, 127, 127, 0.22);
            --mep-sunken: color-mix(in srgb, var(--mep-fg) 14%, var(--mep-bg));
            --mep-border: rgba(127, 127, 127, 0.42);
            --mep-border: color-mix(in srgb, var(--mep-fg) 26%, var(--mep-bg));
            /* Dividers can be a hairline, but anything outlining a control
               needs 3:1 against its own background (WCAG 1.4.11). */
            --mep-border-strong: rgba(127, 127, 127, 0.75);
            --mep-border-strong: color-mix(in srgb, var(--mep-fg) 48%, var(--mep-bg));

            width: 100%; height: 100%; display: flex; flex-direction: column;
            box-sizing: border-box; color: var(--mep-text);
            font-family: sans-serif; font-size: var(--mep-pb-font);
        }
        .zd-pb-toolbar {
            display: flex; align-items: center; gap: 6px; padding: 0 2px 6px 2px;
            font-size: calc(var(--mep-pb-font) - 2px); color: var(--mep-text-muted);
            flex: 0 0 auto;
        }
        .zd-pb-status { margin-right: auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .zd-pb-toolbar button, .zd-pb-restore button {
            background: var(--mep-raised); border: 1px solid var(--mep-border-strong);
            border-radius: 6px; color: var(--mep-text); padding: 3px 10px;
            font-size: calc(var(--mep-pb-font) - 2px); cursor: pointer;
            transition: background 0.12s ease, border-color 0.12s ease;
        }
        .zd-pb-toolbar button:hover, .zd-pb-restore button:hover { background: var(--mep-sunken); }
        .zd-pb-toolbar button.active {
            background: var(--mep-accent); border-color: var(--mep-accent); color: #fff;
        }
        .zd-pb-main { flex: 1 1 auto; min-height: 0; display: flex; gap: 8px; }

        .zd-pb-rail {
            flex: 0 0 132px; min-width: 0; overflow-y: auto; overflow-x: hidden;
            background: var(--mep-panel); border: 1px solid var(--mep-border);
            border-radius: 8px; padding: 4px; box-sizing: border-box;
            scrollbar-width: thin; scrollbar-color: var(--mep-border) transparent;
        }
        .zd-pb-rail.hidden { display: none; }
        .zd-pb-version {
            display: block; width: 100%; text-align: left; cursor: pointer;
            background: none; border: 1px solid transparent; border-radius: 6px;
            color: var(--mep-text); padding: 4px 6px; margin-bottom: 2px;
            font: inherit; font-size: calc(var(--mep-pb-font) - 3px); line-height: 1.35;
        }
        .zd-pb-version:hover { background: var(--mep-raised); }
        .zd-pb-version.selected { background: var(--mep-sunken); border-color: var(--mep-border-strong); }
        .zd-pb-version-head { display: flex; gap: 6px; align-items: baseline; }
        .zd-pb-version-index { font-weight: 600; }
        .zd-pb-version-time { margin-left: auto; color: var(--mep-text-muted); }
        .zd-pb-version-note { color: var(--mep-text-muted); }
        .zd-pb-chips { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 3px; }
        .zd-pb-chip {
            border-radius: 4px; padding: 0 4px; font-size: calc(var(--mep-pb-font) - 5px);
            border: 1px solid var(--mep-border); color: var(--mep-text-muted);
        }
        .zd-pb-chip.added { border-color: #16a34a; color: #16a34a; }
        .zd-pb-chip.modified { border-color: var(--mep-accent); color: var(--mep-accent); }
        .zd-pb-chip.removed { border-color: #dc2626; color: #dc2626; }

        .zd-pb-pane {
            flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column;
            background: var(--mep-panel); border: 1px solid var(--mep-border);
            border-radius: 8px; box-sizing: border-box;
        }
        .zd-pb-restore {
            display: flex; align-items: center; gap: 8px; flex: 0 0 auto;
            padding: 6px 10px; border-bottom: 1px solid var(--mep-border);
            font-size: calc(var(--mep-pb-font) - 3px); color: var(--mep-text-muted);
        }
        .zd-pb-restore.hidden { display: none; }
        .zd-pb-restore span { margin-right: auto; }
        .zd-pb-errors {
            flex: 0 0 auto; padding: 6px 10px; color: var(--mep-warn);
            border-bottom: 1px solid var(--mep-border);
            font-size: calc(var(--mep-pb-font) - 3px); white-space: pre-wrap;
        }
        .zd-pb-errors.hidden { display: none; }
        .zd-pb-body {
            flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden;
            padding: 10px; box-sizing: border-box; line-height: 1.55;
            scrollbar-width: thin; scrollbar-color: var(--mep-border) transparent;
        }
        .zd-pb-body::-webkit-scrollbar, .zd-pb-rail::-webkit-scrollbar { width: 10px; }
        .zd-pb-body::-webkit-scrollbar-thumb, .zd-pb-rail::-webkit-scrollbar-thumb {
            background: var(--mep-border); border-radius: 5px;
            border: 3px solid transparent; background-clip: content-box;
        }
        .zd-pb-empty { color: var(--mep-text-muted); font-style: italic; }
        .zd-pb-section { margin-bottom: 10px; }
        .zd-pb-section:last-child { margin-bottom: 0; }
        .zd-pb-section-name { font-weight: 700; }
        .zd-pb-section-text { white-space: pre-wrap; }
        /* A rule, not a fill: the marker has to survive whatever colour the
           theme paints behind it. */
        .zd-pb-section.touched {
            border-left: 3px solid var(--mep-accent); padding-left: 8px; margin-left: -11px;
        }
        .zd-pb-raw {
            white-space: pre-wrap; font-family: monospace;
            font-size: calc(var(--mep-pb-font) - 1px);
        }
    `;
    document.head.appendChild(style);
}

// --- state -------------------------------------------------------------

function stateOf(node) {
    return (node._zdPb ??= {
        promptId: null,
        revision: 0,
        sections: [],
        history: [],
        errors: [],
        selected: null, // version index being viewed; null = current
        showRaw: false,
        showHistory: true,
    });
}

function selectedVersion(node) {
    const s = stateOf(node);
    if (s.selected == null) return null;
    return s.history.find((v) => v.index === s.selected) ?? null;
}

function visibleSections(node) {
    return selectedVersion(node)?.sections ?? stateOf(node).sections;
}

// --- rendering ---------------------------------------------------------

function renderRail(node) {
    const view = node._zdPbView;
    const s = stateOf(node);
    view.rail.classList.toggle("hidden", !s.showHistory);
    if (!s.showHistory) return;

    view.rail.replaceChildren();
    if (s.history.length === 0) {
        const empty = document.createElement("div");
        empty.className = "zd-pb-empty";
        empty.style.padding = "6px";
        empty.style.fontSize = "calc(var(--mep-pb-font) - 3px)";
        empty.textContent = "No versions yet.";
        view.rail.appendChild(empty);
        return;
    }

    // Newest first: the version you want is nearly always the last one, and a
    // rail that grows downward would push it off the bottom.
    for (const version of [...s.history].reverse()) {
        const isCurrent = version.index === s.revision;
        const button = document.createElement("button");
        button.className = "zd-pb-version";
        button.classList.toggle("selected", (s.selected ?? s.revision) === version.index);
        button.title = version.text || "(empty)";

        const head = document.createElement("div");
        head.className = "zd-pb-version-head";
        const index = document.createElement("span");
        index.className = "zd-pb-version-index";
        index.textContent = `v${version.index}`;
        const time = document.createElement("span");
        time.className = "zd-pb-version-time";
        time.textContent = formatTime(version.time);
        head.append(index, time);
        button.appendChild(head);

        const note = document.createElement("div");
        note.className = "zd-pb-version-note";
        note.textContent = isCurrent ? `${version.note ?? ""} · current` : version.note ?? "";
        button.appendChild(note);

        const chips = document.createElement("div");
        chips.className = "zd-pb-chips";
        for (const [kind, names] of [
            ["added", version.added],
            ["modified", version.modified],
            ["removed", version.removed],
        ]) {
            for (const name of names ?? []) {
                const chip = document.createElement("span");
                chip.className = `zd-pb-chip ${kind}`;
                chip.textContent = name;
                chip.title = `${kind} in v${version.index}`;
                chips.appendChild(chip);
            }
        }
        if (chips.childElementCount) button.appendChild(chips);

        button.addEventListener("click", () => {
            // Clicking the current version clears the selection rather than
            // pinning it, so the panel goes back to following new runs.
            s.selected = isCurrent ? null : version.index;
            renderAll(node);
        });
        view.rail.appendChild(button);
    }
}

function renderPane(node) {
    const view = node._zdPbView;
    const s = stateOf(node);
    const version = selectedVersion(node);
    const sections = visibleSections(node);

    const stale = version != null && version.index !== s.revision;
    view.restore.classList.toggle("hidden", !stale);
    if (stale) view.restoreLabel.textContent = `Viewing v${version.index} of ${s.revision}`;

    view.errors.classList.toggle("hidden", s.errors.length === 0);
    if (s.errors.length) view.errors.textContent = s.errors.join("\n");

    view.body.replaceChildren();
    if (!sections.length) {
        const empty = document.createElement("div");
        empty.className = "zd-pb-empty";
        empty.textContent = "No sections yet - queue the graph with a document to build the prompt.";
        view.body.appendChild(empty);
        return;
    }

    if (s.showRaw) {
        const raw = document.createElement("div");
        raw.className = "zd-pb-raw";
        raw.textContent = version?.text ?? renderPromptText(sections);
        view.body.appendChild(raw);
        return;
    }

    // What the version being viewed touched, so an update reads at a glance.
    const touched = new Set(
        [
            ...(version?.added ?? []),
            ...(version?.modified ?? []),
        ].map((n) => n.trim().toLowerCase())
    );
    for (const section of sections) {
        const el = document.createElement("div");
        el.className = "zd-pb-section";
        if (touched.has(String(section.name).trim().toLowerCase())) el.classList.add("touched");
        const name = document.createElement("span");
        name.className = "zd-pb-section-name";
        name.textContent = section.name;
        const text = document.createElement("span");
        text.className = "zd-pb-section-text";
        text.textContent = `: ${String(section.content ?? "").trim()}`;
        el.append(name, text);
        view.body.appendChild(el);
    }
}

function renderAll(node) {
    const view = node._zdPbView;
    if (!view) return;
    const s = stateOf(node);
    const count = visibleSections(node).length;
    view.status.textContent =
        `v${s.revision} · ${count} section${count === 1 ? "" : "s"} · ` +
        `${s.history.length} version${s.history.length === 1 ? "" : "s"}`;
    renderRail(node);
    renderPane(node);
}

// --- server ------------------------------------------------------------

function applyState(node, data) {
    if (!data) return false;
    const s = stateOf(node);
    s.promptId = data.prompt_id ?? s.promptId;
    s.revision = data.revision ?? 0;
    s.sections = Array.isArray(data.sections) ? data.sections : [];
    s.history = Array.isArray(data.history) ? data.history : [];
    s.errors = Array.isArray(data.errors) ? data.errors : [];
    // A version that no longer exists (history trimmed, state cleared) would
    // otherwise leave the pane pinned to nothing.
    if (s.selected != null && !s.history.some((v) => v.index === s.selected)) s.selected = null;
    renderAll(node);
    return true;
}

function applyPayload(node, raw) {
    if (!raw) return false;
    try {
        return applyState(node, JSON.parse(raw));
    } catch (e) {
        console.warn("[MiseEnPlace Prompt] failed to parse state payload", e);
        return false;
    }
}

// A reload leaves app.nodeOutputs empty, but the server still holds the state -
// so fall back to asking it.
async function loadState(node) {
    if (applyPayload(node, app.nodeOutputs?.[String(node.id)]?.prompt_state?.[0])) return;
    try {
        const params = new URLSearchParams({ prompt_id: resolvePromptId(node) });
        const response = await api.fetchApi(`/miseenplace/prompt_builder/state?${params}`);
        if (!response.ok) return;
        applyState(node, await response.json());
    } catch (e) {
        console.warn("[MiseEnPlace Prompt] failed to load state", e);
    }
}

async function post(node, path, body) {
    try {
        const response = await api.fetchApi(`/miseenplace/prompt_builder/${path}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ prompt_id: resolvePromptId(node), ...body }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (e) {
        console.warn(`[MiseEnPlace Prompt] ${path} failed`, e);
        return null;
    }
}

async function clearState(node) {
    const data = await post(node, "clear", {});
    // Drop the stale cached payload too, or the next reload restores what was
    // just cleared.
    delete app.nodeOutputs?.[String(node.id)];
    stateOf(node).selected = null;
    applyState(node, data ?? { prompt_id: resolvePromptId(node), revision: 0, sections: [], history: [] });
}

async function restoreVersion(node) {
    const version = selectedVersion(node);
    if (!version) return;
    const data = await post(node, "restore", { index: version.index });
    if (!data || data.error) return;
    // The restore landed as a new version; follow it instead of staying pinned
    // to the old one, which is now just history again.
    stateOf(node).selected = null;
    delete app.nodeOutputs?.[String(node.id)];
    applyState(node, data);
}

function copyPrompt(node) {
    const version = selectedVersion(node);
    const text = version?.text ?? renderPromptText(visibleSections(node));
    navigator.clipboard?.writeText(text).catch((e) => {
        console.warn("[MiseEnPlace Prompt] clipboard write failed", e);
    });
}

// --- widget ------------------------------------------------------------

// A widget whose input is linked stops being drawn - DOMWidgetImpl.isVisible()
// is false once computedDisabled is set, and a link sets it - but it still
// occupies its full height in the layout, because _arrangeWidgets works off
// getLayoutWidgets(), which filters on `hidden` alone. For `prompt_json` that
// is a multiline textarea worth of blank space. Hiding it outright while it is
// driven by a link takes it out of both passes.
function syncSourceWidget(node) {
    const widget = node.widgets?.find((w) => w.name === SOURCE_WIDGET);
    if (!widget) return;
    const linked = node.inputs?.find((i) => i.name === SOURCE_WIDGET)?.link != null;
    if (!!widget.hidden === linked) return;

    // Resize by the delta rather than snapping to computeSize(), so any extra
    // room dragged out for the panel survives. The floor keeps a freshly loaded
    // node - whose saved size already excluded the widget - from shrinking twice.
    const before = node.computeSize()[1];
    widget.hidden = linked;
    const after = node.computeSize()[1];
    node.setSize([node.size[0], Math.max(after, node.size[1] + (after - before))]);
    node.graph?.setDirtyCanvas(true, true);
}

function button(label, title, onClick) {
    const el = document.createElement("button");
    el.textContent = label;
    el.title = title;
    el.addEventListener("click", onClick);
    return el;
}

function buildPanel(node) {
    ensureStyles();
    const s = stateOf(node);

    const wrapper = document.createElement("div");
    wrapper.className = "zd-pb";

    const toolbar = document.createElement("div");
    toolbar.className = "zd-pb-toolbar";
    const status = document.createElement("span");
    status.className = "zd-pb-status";
    toolbar.appendChild(status);

    const historyBtn = button("History", "Show or hide the version rail", () => {
        s.showHistory = !s.showHistory;
        historyBtn.classList.toggle("active", s.showHistory);
        renderAll(node);
    });
    historyBtn.classList.add("active");
    const rawBtn = button("Raw", "Toggle between the sections and the exact prompt text", () => {
        s.showRaw = !s.showRaw;
        rawBtn.classList.toggle("active", s.showRaw);
        renderPane(node);
    });
    toolbar.append(
        historyBtn,
        rawBtn,
        button("Copy", "Copy the prompt shown to the clipboard", () => copyPrompt(node)),
        button("Clear", "Discard the prompt and its whole history on the server", () => clearState(node))
    );
    wrapper.appendChild(toolbar);

    const main = document.createElement("div");
    main.className = "zd-pb-main";

    const rail = document.createElement("div");
    rail.className = "zd-pb-rail";
    rail.addEventListener("wheel", (e) => e.stopPropagation());

    const pane = document.createElement("div");
    pane.className = "zd-pb-pane";

    const restore = document.createElement("div");
    restore.className = "zd-pb-restore hidden";
    const restoreLabel = document.createElement("span");
    restore.append(
        restoreLabel,
        button("Restore", "Make this version the current prompt again", () => restoreVersion(node))
    );

    const errors = document.createElement("div");
    errors.className = "zd-pb-errors hidden";

    const body = document.createElement("div");
    body.className = "zd-pb-body";
    // Otherwise the canvas swallows the wheel event and zooms instead.
    body.addEventListener("wheel", (e) => e.stopPropagation());

    pane.append(restore, errors, body);
    main.append(rail, pane);
    wrapper.appendChild(main);

    node._zdPbView = { status, rail, body, restore, restoreLabel, errors };

    // Only a minimum is declared: _arrangeWidgets distributes the node's spare
    // body height across DOM widgets between their min and max, so leaving the
    // max open lets the panel grow when the node is resized.
    node.addDOMWidget("prompt_view", "div", wrapper, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => MIN_VIEW_HEIGHT,
    });

    // computeSize() already accounts for every visible widget, DOM widgets
    // included (via computeLayoutSize), so let it do the arithmetic rather than
    // estimating row heights.
    const [width, height] = node.computeSize();
    node.setSize([Math.max(node.size[0], width), Math.max(node.size[1], height)]);

    // Retargeting the node at another prompt_id should show that prompt, not
    // sit on the previous one's history until the next run.
    const idWidget = node.widgets?.find((w) => w.name === "prompt_id");
    if (idWidget) {
        const previous = idWidget.callback;
        idWidget.callback = function (...args) {
            previous?.apply(this, args);
            stateOf(node).selected = null;
            delete app.nodeOutputs?.[String(node.id)];
            loadState(node);
        };
    }

    renderAll(node);
    loadState(node);
    syncSourceWidget(node);
}

app.registerExtension({
    name: "MiseEnPlace.PromptBuilder",
    // onExecuted is a real per-node execution callback that ComfyUI's result
    // dispatcher calls directly on the instance, so prototype-level patching is
    // reliable here (unlike onNodeCreated - see nodeCreated below).
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            // A run supersedes whatever old version was being inspected.
            stateOf(this).selected = null;
            applyPayload(this, message?.prompt_state?.[0]);
        };
    },
    // Per-instance widget setup belongs here: ComfyUI's node constructor
    // dispatches to extensions' `nodeCreated` hook directly and never calls
    // `this.onNodeCreated?.()`, so a prototype-patched onNodeCreated never runs.
    async afterConfigureGraph() {
        // Links are restored after nodeCreated ran, so a node that loads with
        // `prompt_json` already wired needs one pass once loading has finished.
        for (const node of app.graph?.nodes ?? app.graph?._nodes ?? []) {
            if (node.type === NODE_NAME) syncSourceWidget(node);
        }
    },
    async nodeCreated(node) {
        if (node.comfyClass !== NODE_NAME) return;
        buildPanel(node);
        const previous = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            previous?.apply(this, args);
            if (!app.configuringGraph) syncSourceWidget(this);
        };
    },
});
