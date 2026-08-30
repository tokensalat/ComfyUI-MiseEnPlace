// Three levels up, not two: WEB_DIRECTORY is "./web" and these live in
// web/js/, so they are served from /extensions/ComfyUI-MiseEnPlace/js/ .
// "../../scripts/app.js" (what packs whose files sit one level shallower
// use) resolves to /extensions/scripts/app.js, 404s, and silently stops
// the whole module - and therefore the extension - from loading.
import { app } from "../../../scripts/app.js";

// Nodes that accept an LLM_CONFIG on a "config" input.
const CONSUMER_NODES = new Set(["LlamaCppClient", "LlamaCppChatSession"]);
const CONFIG_INPUT_NAME = "config";

// Keep in sync with SHARED_FIELDS in nodes/llm/_llm_config.py - these are the
// widgets a connected config takes over. Prompts are deliberately absent: they
// stay on the calling node, so they must stay live even with a config wired in.
const COVERED_WIDGETS = new Set([
    "url",
    "timeout",
    "temperature",
    "repeat_penalty",
    "top_k",
    "top_p",
    "min_p",
    "presence_penalty",
    "min_image_tokens",
    "max_image_tokens",
    "do_image_splitting",
    "seed",
]);

function hasConfigConnected(node) {
    return node.inputs?.find((i) => i.name === CONFIG_INPUT_NAME)?.link != null;
}

// litegraph derives computedDisabled from widget.disabled and draws those at
// half alpha while refusing to hit-test them, which is exactly the "this value
// is coming from somewhere else now" affordance we want. The original label is
// stashed so disconnecting puts it back verbatim.
function setCovered(widget, covered) {
    if (covered) {
        if (widget._zdBaseLabel === undefined) widget._zdBaseLabel = widget.label ?? null;
        widget.disabled = true;
        widget.label = `${widget._zdBaseLabel ?? widget.name} (from config)`;
    } else {
        widget.disabled = false;
        if (widget._zdBaseLabel !== undefined) {
            widget.label = widget._zdBaseLabel ?? undefined;
            delete widget._zdBaseLabel;
        }
    }
}

function refresh(node) {
    const covered = hasConfigConnected(node);
    for (const widget of node.widgets ?? []) {
        if (COVERED_WIDGETS.has(widget.name)) setCovered(widget, covered);
    }
    node.graph?.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: "MiseEnPlace.LlmConfigLink",
    async afterConfigureGraph() {
        // Socket links are restored after nodeCreated ran, so a workflow that
        // loads with a config already wired needs one pass once loading ends.
        for (const node of app.graph?.nodes ?? app.graph?._nodes ?? []) {
            if (CONSUMER_NODES.has(node.type)) refresh(node);
        }
    },
    // Per-instance patching, as elsewhere in this pack: ComfyUI's node
    // constructor dispatches to `nodeCreated` directly and never calls
    // `this.onNodeCreated?.()`, so a prototype-patched one never runs.
    async nodeCreated(node) {
        if (!CONSUMER_NODES.has(node.comfyClass)) return;
        const previous = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            previous?.apply(this, args);
            if (!app.configuringGraph) refresh(this);
        };
        refresh(node);
    },
});
