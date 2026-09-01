// Three levels up, not two: WEB_DIRECTORY is "./web" and these live in
// web/js/, so they are served from /extensions/ComfyUI-MiseEnPlace/js/ .
// "../../scripts/app.js" (what packs whose files sit one level shallower
// use) resolves to /extensions/scripts/app.js, 404s, and silently stops
// the whole module - and therefore the extension - from loading.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const NODE_NAME = "JinjaTemplate";
const TEMPLATE_WIDGET = "template";

// Long enough not to re-parse on every keystroke, short enough that the
// sockets appear while you are still looking at the template.
const DEBOUNCE_MS = 400;

// Marks the sockets this extension owns, so the node's real schema inputs are
// never mistaken for placeholders and removed.
const OWNED = "_zdJinjaVar";

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function ownedInputs(node) {
    return (node.inputs ?? []).filter((input) => input[OWNED]);
}

// Asks the server what the template actually resolves to. Parsing happens
// there, against the same jinja2 that renders it, so the sockets can't
// disagree with what the node will look up at render time.
async function fetchVariables(template) {
    const response = await api.fetchApi("/miseenplace/jinja/variables", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

function applyVariables(node, names) {
    const wanted = new Set(names);
    let changed = false;

    // Remove first, so a rename frees its socket before the new one is added.
    // Iterating backwards keeps the indices valid as entries are spliced out.
    const owned = ownedInputs(node);
    for (let i = owned.length - 1; i >= 0; i--) {
        if (wanted.has(owned[i].name)) continue;
        const slot = node.inputs.indexOf(owned[i]);
        if (slot !== -1) {
            node.removeInput(slot);
            changed = true;
        }
    }

    // Append rather than rebuild in template order: reordering would mean
    // tearing down every socket and re-establishing its link, and a dropped
    // link is a worse outcome than a socket list that drifts from the text.
    const present = new Set(ownedInputs(node).map((input) => input.name));
    for (const name of names) {
        if (present.has(name)) continue;
        node.addInput(name, "*");
        node.inputs[node.inputs.length - 1][OWNED] = true;
        changed = true;
    }

    if (changed) {
        // Grow only, never shrink: computeSize() is the node's natural
        // minimum height, and assigning it unconditionally snapped away any
        // manual resize the moment a placeholder was added or removed.
        const minHeight = node.computeSize()[1];
        if (node.size[1] < minHeight) node.size[1] = minHeight;
        node.graph?.setDirtyCanvas(true, true);
    }
    return changed;
}

function notify(detail, severity = "warn") {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary: "Jinja Template", detail, life: 4000 });
    } else {
        console.warn(`[MiseEnPlace Jinja] ${detail}`);
    }
}

async function syncSockets(node, { quiet = true } = {}) {
    const template = getWidget(node, TEMPLATE_WIDGET)?.value ?? "";
    try {
        const { variables, error } = await fetchVariables(template);
        if (error) {
            // A half-typed template is a normal intermediate state, so leave
            // the sockets alone and only speak up on an explicit sync.
            if (!quiet) notify(`Template doesn't parse: ${error}`);
            return;
        }
        applyVariables(node, variables ?? []);
    } catch (e) {
        if (!quiet) notify(`Could not read the template's placeholders: ${e}`);
        console.warn("[MiseEnPlace Jinja] variable lookup failed", e);
    }
}

function scheduleSync(node) {
    clearTimeout(node._zdJinjaTimer);
    node._zdJinjaTimer = setTimeout(() => syncSockets(node), DEBOUNCE_MS);
}

app.registerExtension({
    name: "MiseEnPlace.JinjaTemplate",
    async afterConfigureGraph() {
        // Saved sockets come back from the workflow, but the template may have
        // been edited elsewhere - reconcile once loading has finished. The
        // sockets themselves carry no marker in the saved JSON, so re-tag
        // anything that isn't a schema input before reconciling.
        for (const node of app.graph?.nodes ?? app.graph?._nodes ?? []) {
            if (node.type !== NODE_NAME) continue;
            const schemaInputs = new Set([TEMPLATE_WIDGET, "strict"]);
            for (const input of node.inputs ?? []) {
                if (!schemaInputs.has(input.name)) input[OWNED] = true;
            }
            syncSockets(node);
        }
    },
    async nodeCreated(node) {
        if (node.comfyClass !== NODE_NAME) return;

        const widget = getWidget(node, TEMPLATE_WIDGET);
        if (widget) {
            const callback = widget.callback;
            widget.callback = function (...args) {
                const result = callback?.apply(this, args);
                if (!app.configuringGraph) scheduleSync(node);
                return result;
            };
        }

        // The widget callback is the primary trigger, but a DOM textarea's
        // wiring differs across frontend versions - a manual sync means the
        // node is never stuck with stale sockets.
        node.addWidget("button", "🔄 Sync Placeholders", null, () => syncSockets(node, { quiet: false }), {
            serialize: false,
        });
        node.size[1] = node.computeSize()[1];

        if (!app.configuringGraph) syncSockets(node);
    },
});
