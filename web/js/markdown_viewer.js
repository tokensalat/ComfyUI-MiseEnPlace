// Three levels up, not two: WEB_DIRECTORY is "./web" and these live in
// web/js/, so they are served from /extensions/ComfyUI-MiseEnPlace/js/ .
// "../../scripts/app.js" (what packs whose files sit one level shallower
// use) resolves to /extensions/scripts/app.js, 404s, and silently stops
// the whole module - and therefore the extension - from loading.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
// Vendored so the node works with no internet access - see vendor/README.md.
import { marked } from "./vendor/marked.esm.mjs";
import DOMPurify from "./vendor/purify.es.mjs";

const NODE_NAME = "MarkdownViewer";
// The multiline widget that doubles as the text input socket.
const SOURCE_WIDGET = "markdown";
const MIN_VIEW_HEIGHT = 240;

// Base type size for the viewer; every other size derives from it via the
// --mep-md-font custom property, so this one number tunes the lot.
const VIEWER_FONT_SIZE = 14;

marked.setOptions({
    gfm: true,
    breaks: true, // chat/LLM text uses single newlines as real line breaks
});

// marked emits raw HTML that appears in the markdown verbatim, and the text
// here comes from a model or an arbitrary upstream node - so everything it
// produces goes through DOMPurify before it is put into the document.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A" && node.hasAttribute("href")) {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
    }
});

function renderMarkdown(text) {
    return DOMPurify.sanitize(marked.parse(String(text ?? "")));
}

function formatTime(epochSeconds) {
    if (!epochSeconds) return "";
    return new Date(epochSeconds * 1000).toLocaleTimeString();
}

// The id the Python side derives when the history_id widget is left blank
// (MarkdownViewer._resolve_history_id).
function resolveHistoryId(node) {
    const explicit = node.widgets?.find((w) => w.name === "history_id")?.value;
    const trimmed = typeof explicit === "string" ? explicit.trim() : "";
    return trimmed || `__node_${node.id}`;
}

let stylesInjected = false;
function ensureStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    const style = document.createElement("style");
    style.textContent = `
        /* Same token scheme as the chat window: derived from ComfyUI's
           --fg-color/--bg-color, which :root sets for the light theme and
           .dark-theme flips, so this reads correctly under both. The plain
           value above each color-mix() is the fallback for browsers that
           can't parse it. */
        .zd-md-viewer {
            --mep-md-font: ${VIEWER_FONT_SIZE}px;
            --mep-fg: var(--fg-color, #e6e6e6);
            --mep-bg: var(--bg-color, #202020);
            --mep-accent: #2563eb;

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
            /* Dividers can be a hairline, but anything that outlines a
               control needs 3:1 against its own background (WCAG 1.4.11). */
            --mep-border-strong: rgba(127, 127, 127, 0.75);
            --mep-border-strong: color-mix(in srgb, var(--mep-fg) 48%, var(--mep-bg));

            width: 100%; height: 100%; display: flex; flex-direction: column;
            box-sizing: border-box; color: var(--mep-text);
        }
        .zd-md-toolbar {
            display: flex; align-items: center; gap: 6px; padding: 0 2px 6px 2px;
            font-family: sans-serif; font-size: calc(var(--mep-md-font) - 2px);
            color: var(--mep-text-muted); flex: 0 0 auto;
        }
        .zd-md-count { margin-right: auto; }
        .zd-md-toolbar button {
            background: var(--mep-raised); border: 1px solid var(--mep-border-strong);
            border-radius: 6px; color: var(--mep-text); padding: 3px 10px;
            font-size: calc(var(--mep-md-font) - 2px); cursor: pointer;
            transition: background 0.12s ease, border-color 0.12s ease;
        }
        .zd-md-toolbar button:hover { background: var(--mep-sunken); }
        .zd-md-toolbar button.active {
            background: var(--mep-accent); border-color: var(--mep-accent); color: #fff;
        }
        .zd-md-body {
            flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden;
            background: var(--mep-panel); border: 1px solid var(--mep-border);
            border-radius: 8px; padding: 10px; box-sizing: border-box;
            font-family: sans-serif; font-size: var(--mep-md-font);
            line-height: 1.6; color: var(--mep-text);
            scrollbar-width: thin;
            scrollbar-color: var(--mep-border) transparent;
        }
        .zd-md-body::-webkit-scrollbar { width: 10px; }
        .zd-md-body::-webkit-scrollbar-thumb {
            background: var(--mep-border); border-radius: 5px;
            border: 3px solid transparent; background-clip: content-box;
        }
        .zd-md-empty { color: var(--mep-text-muted); font-style: italic; }
        .zd-md-entry { padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid var(--mep-border); }
        .zd-md-entry:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
        .zd-md-entry-head {
            display: flex; gap: 8px; align-items: baseline;
            font-size: calc(var(--mep-md-font) - 3px); color: var(--mep-text-muted);
            margin-bottom: 5px; letter-spacing: 0.03em;
        }
        .zd-md-entry-heading { color: var(--mep-text); font-weight: 600; letter-spacing: 0; }
        .zd-md-entry-time { margin-left: auto; }
        .zd-md-source {
            white-space: pre-wrap; font-family: monospace;
            font-size: calc(var(--mep-md-font) - 1px); color: var(--mep-text);
        }
        .zd-md-content > :first-child { margin-top: 0; }
        .zd-md-content > :last-child { margin-bottom: 0; }
        .zd-md-content h1, .zd-md-content h2, .zd-md-content h3,
        .zd-md-content h4, .zd-md-content h5, .zd-md-content h6 {
            margin: 12px 0 5px 0; line-height: 1.3; color: var(--mep-text);
        }
        .zd-md-content h1 { font-size: calc(var(--mep-md-font) + 5px); }
        .zd-md-content h2 { font-size: calc(var(--mep-md-font) + 3px); }
        .zd-md-content h3 { font-size: calc(var(--mep-md-font) + 1px); }
        .zd-md-content h4, .zd-md-content h5, .zd-md-content h6 { font-size: var(--mep-md-font); }
        .zd-md-content p { margin: 0 0 8px 0; }
        .zd-md-content ul, .zd-md-content ol { margin: 4px 0 8px 0; padding-left: 22px; }
        .zd-md-content li { margin: 3px 0; }
        .zd-md-content pre {
            background: var(--mep-sunken); padding: 9px; border-radius: 6px;
            overflow-x: auto; margin: 6px 0;
        }
        .zd-md-content code {
            background: var(--mep-sunken); padding: 1px 5px; border-radius: 3px;
            font-family: monospace; font-size: calc(var(--mep-md-font) - 1px);
        }
        .zd-md-content pre code { background: none; padding: 0; }
        .zd-md-content blockquote {
            border-left: 3px solid var(--mep-border); margin: 6px 0;
            padding-left: 12px; color: var(--mep-text-muted);
        }
        .zd-md-content table {
            border-collapse: collapse; margin: 6px 0;
            font-size: calc(var(--mep-md-font) - 1px); display: block; overflow-x: auto;
        }
        .zd-md-content th, .zd-md-content td { border: 1px solid var(--mep-border); padding: 4px 8px; text-align: left; }
        .zd-md-content th { background: var(--mep-raised); }
        .zd-md-content hr { border: none; border-top: 1px solid var(--mep-border); margin: 10px 0; }
        .zd-md-content img { max-width: 100%; border-radius: 6px; }
        .zd-md-content a { color: var(--mep-accent); }
    `;
    document.head.appendChild(style);
}

function renderEntries(node) {
    const view = node._zdMd;
    if (!view) return;
    const entries = node._zdMdEntries ?? [];

    view.count.textContent = entries.length === 1 ? "1 entry" : `${entries.length} entries`;
    view.body.replaceChildren();

    if (entries.length === 0) {
        const empty = document.createElement("div");
        empty.className = "zd-md-empty";
        empty.textContent = "Nothing yet - run the graph to add an entry.";
        view.body.appendChild(empty);
        return;
    }

    // Track whether the user was already at the bottom, so appending an entry
    // follows along but scrolling back to re-read something isn't yanked away.
    const wasAtBottom = view.body.scrollHeight - view.body.scrollTop - view.body.clientHeight < 32;

    for (const entry of entries) {
        const el = document.createElement("div");
        el.className = "zd-md-entry";

        const head = document.createElement("div");
        head.className = "zd-md-entry-head";
        const idx = document.createElement("span");
        idx.textContent = `#${entry.index ?? 0}`;
        head.appendChild(idx);
        if (entry.heading) {
            const heading = document.createElement("span");
            heading.className = "zd-md-entry-heading";
            heading.textContent = entry.heading;
            head.appendChild(heading);
        }
        const time = document.createElement("span");
        time.className = "zd-md-entry-time";
        time.textContent = formatTime(entry.time);
        head.appendChild(time);
        el.appendChild(head);

        const content = document.createElement("div");
        if (node._zdMdShowSource) {
            content.className = "zd-md-source";
            content.textContent = entry.text ?? "";
        } else {
            content.className = "zd-md-content";
            content.innerHTML = renderMarkdown(entry.text);
        }
        el.appendChild(content);
        view.body.appendChild(el);
    }

    if (wasAtBottom) view.body.scrollTop = view.body.scrollHeight;
}

function setEntries(node, entries) {
    node._zdMdEntries = Array.isArray(entries) ? entries : [];
    renderEntries(node);
}

function applyPayload(node, raw) {
    if (!raw) return false;
    try {
        setEntries(node, JSON.parse(raw).entries);
        return true;
    } catch (e) {
        console.warn("[MiseEnPlace Markdown] failed to parse history payload", e);
        return false;
    }
}

// A reload leaves app.nodeOutputs empty, but the server still holds the
// history - so fall back to asking it.
async function loadHistory(node) {
    if (applyPayload(node, app.nodeOutputs?.[String(node.id)]?.markdown_history?.[0])) return;
    try {
        const params = new URLSearchParams({ history_id: resolveHistoryId(node) });
        const response = await api.fetchApi(`/miseenplace/markdown_viewer/history?${params}`);
        if (!response.ok) return;
        setEntries(node, (await response.json()).entries);
    } catch (e) {
        console.warn("[MiseEnPlace Markdown] failed to load history", e);
    }
}

async function clearHistory(node) {
    try {
        const response = await api.fetchApi("/miseenplace/markdown_viewer/clear", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ history_id: resolveHistoryId(node) }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
    } catch (e) {
        console.warn("[MiseEnPlace Markdown] failed to clear history", e);
    }
    // Drop the stale cached payload too, or the next reload restores what was
    // just cleared.
    delete app.nodeOutputs?.[String(node.id)];
    setEntries(node, []);
}

function copyDocument(node) {
    const text = (node._zdMdEntries ?? [])
        .map((e) => (e.heading ? `## ${e.heading}\n\n${e.text ?? ""}` : e.text ?? ""))
        .join("\n\n");
    navigator.clipboard?.writeText(text).catch((e) => {
        console.warn("[MiseEnPlace Markdown] clipboard write failed", e);
    });
}

// A widget whose input is linked stops being drawn - DOMWidgetImpl.isVisible()
// is false once computedDisabled is set, and a link sets it - but it still
// occupies its full height in the layout, because _arrangeWidgets works off
// getLayoutWidgets(), which filters on `hidden` alone. For the `markdown`
// widget that is a ~200px multiline textarea worth of blank space. Hiding it
// outright while it is driven by a link takes it out of both passes.
function syncSourceWidget(node) {
    const widget = node.widgets?.find((w) => w.name === SOURCE_WIDGET);
    if (!widget) return;
    const linked = node.inputs?.find((i) => i.name === SOURCE_WIDGET)?.link != null;
    if (!!widget.hidden === linked) return;

    // Resize by the delta rather than snapping to computeSize(), so any extra
    // room dragged out for the rendered markdown survives. The floor keeps a
    // freshly loaded node - whose saved size already excluded the widget -
    // from being shrunk twice.
    const before = node.computeSize()[1];
    widget.hidden = linked;
    const after = node.computeSize()[1];
    node.setSize([node.size[0], Math.max(after, node.size[1] + (after - before))]);
    node.graph?.setDirtyCanvas(true, true);
}

function buildViewer(node) {
    ensureStyles();

    const wrapper = document.createElement("div");
    wrapper.className = "zd-md-viewer";

    const toolbar = document.createElement("div");
    toolbar.className = "zd-md-toolbar";
    const count = document.createElement("span");
    count.className = "zd-md-count";
    toolbar.appendChild(count);

    const sourceBtn = document.createElement("button");
    sourceBtn.textContent = "Source";
    sourceBtn.title = "Toggle between rendered markdown and the raw text";
    sourceBtn.addEventListener("click", () => {
        node._zdMdShowSource = !node._zdMdShowSource;
        sourceBtn.classList.toggle("active", node._zdMdShowSource);
        renderEntries(node);
    });
    const copyBtn = document.createElement("button");
    copyBtn.textContent = "Copy";
    copyBtn.title = "Copy the whole accumulated document to the clipboard";
    copyBtn.addEventListener("click", () => copyDocument(node));
    const clearBtn = document.createElement("button");
    clearBtn.textContent = "Clear";
    clearBtn.title = "Discard the history on the server and empty this view";
    clearBtn.addEventListener("click", () => clearHistory(node));
    toolbar.append(sourceBtn, copyBtn, clearBtn);
    wrapper.appendChild(toolbar);

    const body = document.createElement("div");
    body.className = "zd-md-body";
    // Otherwise the canvas swallows the wheel event and zooms instead.
    body.addEventListener("wheel", (e) => e.stopPropagation());
    wrapper.appendChild(body);

    node._zdMd = { body, count };
    node._zdMdShowSource = false;
    node._zdMdEntries = [];

    // Only a minimum is declared: _arrangeWidgets distributes the node's spare
    // body height across DOM widgets between their min and max, so leaving the
    // max open lets the viewer grow when the node is resized. Pinning
    // min == max == height (as the chat window does) freezes it instead.
    node.addDOMWidget("markdown_view", "div", wrapper, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => MIN_VIEW_HEIGHT,
    });

    // computeSize() already accounts for every visible widget, DOM widgets
    // included (via computeLayoutSize), so let it do the arithmetic rather
    // than estimating row heights - an estimate goes badly wrong as soon as
    // the node carries a multiline text widget.
    const [width, height] = node.computeSize();
    node.setSize([Math.max(node.size[0], width), Math.max(node.size[1], height)]);

    renderEntries(node);
    loadHistory(node);
    syncSourceWidget(node);
}

app.registerExtension({
    name: "MiseEnPlace.MarkdownViewer",
    // onExecuted is a real per-node execution callback that ComfyUI's result
    // dispatcher calls directly on the instance, so prototype-level patching
    // is reliable here (unlike onNodeCreated - see nodeCreated below).
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            applyPayload(this, message?.markdown_history?.[0]);
        };
    },
    // Per-instance widget setup belongs here: ComfyUI's node constructor
    // dispatches to extensions' `nodeCreated` hook directly and never calls
    // `this.onNodeCreated?.()`, so a prototype-patched onNodeCreated never runs.
    async afterConfigureGraph() {
        // Links are restored after nodeCreated ran, so a node that loads with
        // `markdown` already wired needs one pass once loading has finished.
        for (const node of app.graph?.nodes ?? app.graph?._nodes ?? []) {
            if (node.type === NODE_NAME) syncSourceWidget(node);
        }
    },
    async nodeCreated(node) {
        if (node.comfyClass !== NODE_NAME) return;
        buildViewer(node);
        const previous = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            previous?.apply(this, args);
            if (!app.configuringGraph) syncSourceWidget(this);
        };
    },
});
