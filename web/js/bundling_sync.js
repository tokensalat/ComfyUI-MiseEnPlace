// Three levels up, not two: WEB_DIRECTORY is "./web" and these live in
// web/js/, so they are served from /extensions/ComfyUI-MiseEnPlace/js/ .
// "../../scripts/app.js" (what packs whose files sit one level shallower
// use) resolves to /extensions/scripts/app.js, 404s, and silently stops
// the whole module - and therefore the extension - from loading.
import { app } from "../../../scripts/app.js";

// Keep in sync with MAX_OUTPUTS in nodes/bundling/unbundler.py. This is the
// ceiling on how many output sockets the node may show, not a fixed bank -
// applyKeysToUnbundler adds and removes them to match the bundle wired in.
const MAX_UNBUNDLER_OUTPUTS = 32;

// Keep in sync with the io_type passed to io.Custom(...) in nodes/bundling/_bundle_type.py
const BUNDLE_TYPE = "MISEENPLACE_BUNDLE";
const BUNDLE_TYPE_COLOR = "#00c2a8";

// Autogrow names each generated slot "<autogrow input id>.<prefix><ordinal>" and gives it
// display_name "<prefix><ordinal>" (frontend: autogrowOrdinalToName). So
// io.Autogrow.Input("items", template=TemplatePrefix(prefix="item", ...)) produces sockets
// whose .name is "items.item0", "items.item1", ... - not the bare "item0" shown on canvas.
// Keep these in sync with the ids used in nodes/bundling/bundler.py and piercer.py.
const BUNDLER_ITEM_PREFIX = "items.item";
const PIERCER_OVERRIDE_PREFIX = "overrides.override";

const DYNAMIC_PREFIXES = { Bundler: BUNDLER_ITEM_PREFIX, Piercer: PIERCER_OVERRIDE_PREFIX };

// Reroutes are pass-through, so their own output slot carries no useful name -
// walk past them to find the node that actually produces the value.
const REROUTE_TYPES = new Set(["Reroute", "RerouteNode", "Reroute (rgthree)"]);

// Per-slot record of the key names *we* auto-assigned, so a later sync can tell
// "still the name we filled in" (safe to overwrite) from "the user typed this"
// (never overwrite). Kept in node.properties because that survives save/load -
// a plain instance field would make every reloaded auto-name look user-chosen.
const AUTO_KEYS_PROP = "zd_auto_keys";

const MAX_TRACE_DEPTH = 32;

function parseKeys(value) {
    if (!value) return [];
    return value.split(",").map((k) => k.trim());
}

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function getWidgetValue(node, name, fallback = "") {
    const widget = getWidget(node, name);
    return widget ? widget.value : fallback;
}

function graphNodes(graph) {
    return graph?.nodes ?? graph?._nodes ?? [];
}

// graph.links is a Map in some litegraph versions and a plain object/array in
// others (and may live under the private `_links` name instead) - graph.getLink()
// is the version-agnostic way to look one up when available.
function getLinkById(graph, linkId) {
    if (linkId == null || !graph) return null;
    if (typeof graph.getLink === "function") return graph.getLink(linkId);
    const links = graph._links ?? graph.links;
    if (!links) return null;
    return links instanceof Map ? links.get(linkId) : links[linkId] ?? null;
}

// --- upstream resolution -------------------------------------------------

// The output slot object a link ultimately comes from, hopping through Reroutes.
// Newer litegraph resolves a link's origin via link.resolve(graph) (needed for
// e.g. subgraph-crossing links); older versions don't have that method, so fall
// back to the direct origin_id/origin_slot lookup in that case.
function traceOriginOutput(node, link, depth = 0) {
    if (!link || depth > MAX_TRACE_DEPTH) return null;
    const graph = node.graph;
    let output = null;
    if (typeof link.resolve === "function") {
        const resolved = link.resolve(graph);
        output = resolved?.subgraphInput ?? resolved?.output ?? null;
    }
    const originNode = graph?.getNodeById(link.origin_id);
    if (!output) output = originNode?.outputs?.[link.origin_slot] ?? null;
    if (originNode && REROUTE_TYPES.has(originNode.type)) {
        const upstreamLink = getLinkById(originNode.graph, originNode.inputs?.[0]?.link);
        const upstream = traceOriginOutput(originNode, upstreamLink, depth + 1);
        if (upstream) return upstream;
    }
    return output;
}

// The node feeding a named input, hopping through Reroutes. Used for "bundle"
// inputs, where we need the Bundler/Piercer itself rather than its output slot.
function getSourceNode(node, inputName) {
    let current = node;
    let linkId = node.inputs?.find((i) => i.name === inputName)?.link;
    for (let depth = 0; depth <= MAX_TRACE_DEPTH; depth++) {
        const link = getLinkById(current.graph, linkId);
        if (!link) return null;
        const origin = current.graph?.getNodeById(link.origin_id);
        if (!origin) return null;
        if (!REROUTE_TYPES.has(origin.type)) return origin;
        current = origin;
        linkId = origin.inputs?.[0]?.link;
    }
    return null;
}

// --- dynamic (Autogrow) socket sync --------------------------------------

function slotOrdinal(name, prefix) {
    if (!name || !name.startsWith(prefix)) return null;
    const rest = name.slice(prefix.length);
    if (!/^\d+$/.test(rest)) return null;
    return Number(rest);
}

// All Autogrow slots for `prefix`, ordered by their numeric suffix rather than
// array order (which should already match, but this makes no assumption).
function getPrefixedSlots(node, prefix) {
    if (!node.inputs) return [];
    return node.inputs
        .map((input) => ({ input, idx: slotOrdinal(input.name, prefix) }))
        .filter((e) => e.idx !== null)
        .sort((a, b) => a.idx - b.idx);
}

function getConnectedPrefixedSlots(node, prefix) {
    return getPrefixedSlots(node, prefix).filter((e) => e.input.link != null);
}

function getAutoKeys(node) {
    node.properties ??= {};
    const existing = node.properties[AUTO_KEYS_PROP];
    if (!existing || typeof existing !== "object") node.properties[AUTO_KEYS_PROP] = {};
    return node.properties[AUTO_KEYS_PROP];
}

function getKeysWidgetEntry(node, index) {
    return parseKeys(getWidgetValue(node, "keys"))[index]?.trim() || "";
}

function setKeysWidgetEntry(node, index, value) {
    const widget = getWidget(node, "keys");
    if (!widget) return;
    const names = parseKeys(widget.value);
    while (names.length <= index) names.push("");
    names[index] = value;
    while (names.length > 0 && !names[names.length - 1]) names.pop();
    widget.value = names.join(", ");
}

// A bundle is a dict, so two slots auto-named from same-named outputs (two
// STRING sockets, say) would silently collapse into one key. Suffix instead.
function uniqueKeyName(node, idx, base) {
    const taken = new Set(
        parseKeys(getWidgetValue(node, "keys"))
            .map((k, i) => (i === idx ? "" : k.trim()))
            .filter(Boolean)
    );
    if (!taken.has(base)) return base;
    for (let n = 2; ; n++) {
        const candidate = `${base}_${n}`;
        if (!taken.has(candidate)) return candidate;
    }
}

// Applies a resolved origin output's type/name onto one dynamic input slot.
// litegraph colours sockets and links by `.type`, so copying the origin's type
// is what makes the socket render in its real colour instead of the generic ANY
// grey; the name is written into the "keys" widget (not just as a cosmetic
// label) so it becomes the actual bundle key on the Python side.
function applyOriginToSlot(node, input, idx, originOutput) {
    const autoKeys = getAutoKeys(node);
    const originType = originOutput?.type || "*";
    input.type = originType;
    const displayName = originOutput?.label || originOutput?.name || (originType !== "*" ? originType : "");
    input.label = displayName || undefined;

    const current = getKeysWidgetEntry(node, idx);
    if (displayName && (!current || current === autoKeys[idx])) {
        const key = uniqueKeyName(node, idx, displayName);
        setKeysWidgetEntry(node, idx, key);
        autoKeys[idx] = key;
    }
}

function resetSlot(node, input, idx) {
    const autoKeys = getAutoKeys(node);
    input.type = "*";
    input.label = undefined;
    if (getKeysWidgetEntry(node, idx) === autoKeys[idx]) setKeysWidgetEntry(node, idx, "");
    delete autoKeys[idx];
}

// Re-derives type/name for every dynamic socket in one pass. Doing the whole
// node (rather than just the slot that changed) keeps things correct when
// Autogrow shuffles links between slots on disconnect, and after a workflow
// load - ComfyNode.configure() restores each input's type from the node
// definition, so saved sockets always come back as "*" until this runs.
function syncDynamicSlots(node, prefix) {
    for (const { input, idx } of getPrefixedSlots(node, prefix)) {
        const link = input.link != null ? getLinkById(node.graph, input.link) : null;
        const origin = link ? traceOriginOutput(node, link) : null;
        if (origin) applyOriginToSlot(node, input, idx, origin);
        else resetSlot(node, input, idx);
    }
}

// --- bundle key resolution -----------------------------------------------

// Mirrors Bundler.execute()'s key-naming fallback (item0, item1, ...): keys are
// indexed by position among the *connected* items, matching the dict Python
// receives. Types come from each socket's live `.type`, kept current by
// syncDynamicSlots.
function resolveBundlerKeys(node) {
    const names = parseKeys(getWidgetValue(node, "keys"));
    return getConnectedPrefixedSlots(node, BUNDLER_ITEM_PREFIX).map(({ input }, i) => {
        const name = names[i]?.trim();
        return { name: name || `item${i}`, type: input.type || "*" };
    });
}

// Mirrors Piercer.execute(): starts from the upstream bundle's keys, then
// appends any override keys that aren't already present (or, for a key that
// already exists upstream, replaces its type too - overriding a value means the
// override's type is what actually ends up in the output bundle).
function resolvePiercerKeys(node, visited) {
    const upstream = resolveBundleKeys(getSourceNode(node, "bundle"), visited);
    if (upstream === null) return null;
    const keys = upstream.map((k) => ({ ...k }));
    const names = parseKeys(getWidgetValue(node, "keys"));
    getConnectedPrefixedSlots(node, PIERCER_OVERRIDE_PREFIX).forEach(({ input }, i) => {
        const name = names[i]?.trim();
        if (!name) return;
        const entry = { name, type: input.type || "*" };
        const existing = keys.findIndex((k) => k.name === name);
        if (existing >= 0) keys[existing] = entry;
        else keys.push(entry);
    });
    return keys;
}

// What keys a BUNDLE produced by `node` currently carries. Returns null if the
// chain can't be resolved (unknown node type feeding the bundle).
function resolveBundleKeys(node, visited = new Set()) {
    if (!node) return [];
    if (visited.has(node.id)) return [];
    visited.add(node.id);
    if (node.type === "Bundler") return resolveBundlerKeys(node);
    if (node.type === "Piercer") return resolvePiercerKeys(node, visited);
    return null;
}

// --- Unbundler -----------------------------------------------------------

// How many sockets the node should show. Grows to the bundle's key count, but
// never shrinks past an output someone has wired up: a bundle key that briefly
// disappears (an item unplugged from the Bundler upstream) would otherwise take
// the downstream link with it. A stale socket keeps its link, reverts to
// value_N/ANY and outputs None, which reads as "this key is gone" rather than
// silently rewiring the graph.
function unbundlerOutputCount(node, keys) {
    let lastLinked = -1;
    (node.outputs ?? []).forEach((output, i) => {
        if (output.links?.length) lastLinked = i;
    });
    return Math.min(Math.max(keys.length, lastLinked + 1, 1), MAX_UNBUNDLER_OUTPUTS);
}

function applyKeysToUnbundler(node, keys, quiet) {
    const widget = getWidget(node, "keys");
    if (widget) {
        widget.value = keys
            .slice(0, MAX_UNBUNDLER_OUTPUTS)
            .map((k) => k.name)
            .join(", ");
    }

    // The node definition declares MAX_UNBUNDLER_OUTPUTS sockets because V3
    // schemas can't grow outputs, but a prompt only records links by slot
    // index - so the canvas is free to show just the ones in use, the way Pipe
    // Unpacker does. Resize before relabelling so every socket gets named.
    node.outputs ??= [];
    const wanted = unbundlerOutputCount(node, keys);
    while (node.outputs.length > wanted) node.removeOutput(node.outputs.length - 1);
    while (node.outputs.length < wanted) node.addOutput(`value_${node.outputs.length + 1}`, "*");

    for (let i = 0; i < node.outputs.length; i++) {
        const key = keys[i];
        node.outputs[i].name = key?.name ?? `value_${i + 1}`;
        node.outputs[i].label = node.outputs[i].name;
        // Existing links are deliberately left alone on a type change: this also
        // runs right after a workflow load (where every output starts out "*"),
        // and disconnecting there would silently tear up the loaded graph.
        node.outputs[i].type = key?.type || "*";
    }
    node.size[1] = node.computeSize()[1];

    if (!quiet && keys.length > MAX_UNBUNDLER_OUTPUTS) {
        notify(
            `Bundle has ${keys.length} keys but Unbundler tops out at ${MAX_UNBUNDLER_OUTPUTS} outputs; extra keys were dropped.`
        );
    }
}

// --- sync entry points ---------------------------------------------------

function notify(message, severity = "warn") {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary: "Bundling Sync", detail: message, life: 4000 });
    } else {
        console.warn(`[MiseEnPlace Bundling] ${message}`);
    }
}

function nodeLabel(node) {
    return node?.title || node?.type || "node";
}

// Syncs one bundling node. For Bundler/Piercer that means refreshing their
// dynamic sockets from whatever is wired into them; for Unbundler it means
// pulling the key list out of the upstream bundle.
function syncNode(node, quiet = false) {
    const prefix = DYNAMIC_PREFIXES[node.type];
    if (prefix) {
        syncDynamicSlots(node, prefix);
        return true;
    }
    if (node.type !== "Unbundler") return false;

    const source = getSourceNode(node, "bundle");
    if (!source) {
        if (!quiet) notify(`${nodeLabel(node)}: connect 'bundle' to a Bundler (or a chain of Piercers) first.`);
        return false;
    }
    const keys = resolveBundleKeys(source);
    if (keys === null) {
        if (!quiet) {
            notify(`${nodeLabel(node)}: could not resolve bundle keys from upstream node '${nodeLabel(source)}'.`);
        }
        return false;
    }
    applyKeysToUnbundler(node, keys, quiet);
    return true;
}

// Bundler/Piercer sockets must be refreshed before Unbundlers read them, but
// beyond that ordering is irrelevant: nothing here overwrites a widget that
// another node reads as its own source of truth.
function syncGraph(graph, quiet) {
    const nodes = graphNodes(graph);
    const producers = nodes.filter((n) => DYNAMIC_PREFIXES[n.type]);
    const unbundlers = nodes.filter((n) => n.type === "Unbundler");
    let synced = 0;
    for (const node of producers) if (syncNode(node, quiet)) synced++;
    for (const node of unbundlers) if (syncNode(node, quiet)) synced++;
    graph?.setDirtyCanvas(true, true);
    return { synced, total: producers.length + unbundlers.length };
}

function syncAllBundlingNodes() {
    const { synced, total } = syncGraph(app.graph, false);
    if (total === 0) {
        notify("No Bundler, Piercer or Unbundler nodes found in this workflow.", "info");
        return;
    }
    notify(`Synced ${synced}/${total} node(s).`, synced === total ? "success" : "warn");
}

// A Bundler/Piercer whose sockets just changed also changes the key list every
// downstream Unbundler shows, so refresh those too - quietly, since this is a
// side effect of wiring something up rather than an explicit sync request.
function syncDownstreamUnbundlers(node) {
    for (const other of graphNodes(node.graph)) {
        if (other.type === "Unbundler") syncNode(other, true);
    }
}

// Autogrow defers its own slot bookkeeping to the next animation frame (when a
// middle slot is disconnected it shifts the remaining links down and re-fires
// onConnectionsChange), so coalesce into one pass that runs after it settles.
function scheduleSync(node, work) {
    if (node._zdSyncQueued) return;
    node._zdSyncQueued = true;
    requestAnimationFrame(() => {
        node._zdSyncQueued = false;
        if (!node.graph) return;
        work();
        node.graph.setDirtyCanvas(true, true);
    });
}

// --- node wiring ---------------------------------------------------------

function addButton(node, label, onClick) {
    // serialize: false - a button has no value, and letting it into
    // widgets_values shifts the "keys" value out of position on reload.
    node.addWidget("button", label, null, onClick, { serialize: false });
    // Widgets are added after the constructor has already sized the node, so
    // grow it or the button lands outside the node body and never renders.
    node.size[1] = node.computeSize()[1];
}

function attachConnectionSync(node, work) {
    const previous = node.onConnectionsChange;
    node.onConnectionsChange = function (side, slot, connected, link, ioSlot) {
        previous?.apply(this, arguments);
        if (app.configuringGraph) return;
        scheduleSync(this, work);
    };
}

// Hand-edited key names change what downstream Unbundlers should show.
function attachKeysWidgetSync(node) {
    const widget = getWidget(node, "keys");
    if (!widget) return;
    const callback = widget.callback;
    widget.callback = function (...args) {
        const result = callback?.apply(this, args);
        if (!app.configuringGraph) scheduleSync(node, () => syncDownstreamUnbundlers(node));
        return result;
    };
}

app.registerExtension({
    name: "MiseEnPlace.BundlingSync",
    commands: [
        {
            id: "MiseEnPlace.Bundling.SyncAll",
            label: "Sync All Bundle Keys",
            function: syncAllBundlingNodes,
        },
    ],
    menuCommands: [
        {
            path: ["MiseEnPlace", "Bundling"],
            commands: ["MiseEnPlace.Bundling.SyncAll"],
        },
    ],
    async afterConfigureGraph() {
        if (app.canvas?.default_connection_color_byType) {
            app.canvas.default_connection_color_byType[BUNDLE_TYPE] = BUNDLE_TYPE_COLOR;
        }
        if (typeof LGraphCanvas !== "undefined" && LGraphCanvas.link_type_colors) {
            LGraphCanvas.link_type_colors[BUNDLE_TYPE] = BUNDLE_TYPE_COLOR;
        }
        // Socket types are not round-tripped: ComfyNode.configure() re-reads
        // each slot's type from the node definition, so every dynamic socket
        // comes back as "*". Re-derive the whole graph once loading is done.
        syncGraph(app.graph, true);
    },
    // Per-instance setup belongs in nodeCreated, not in an `onNodeCreated`
    // prototype patch: ComfyUI's node constructor dispatches to extensions'
    // `nodeCreated` hook directly and does not call `this.onNodeCreated?.()`.
    // onConnectionsChange is patched per instance too - the Autogrow frontend
    // installs its own handler as an own property during construction, so
    // chaining onto the instance is what keeps us running after its bookkeeping.
    async nodeCreated(node) {
        const prefix = DYNAMIC_PREFIXES[node.comfyClass];
        if (prefix) {
            const work = () => {
                syncDynamicSlots(node, prefix);
                syncDownstreamUnbundlers(node);
            };
            attachConnectionSync(node, work);
            attachKeysWidgetSync(node);
            addButton(node, "🔄 Sync Types", () => {
                work();
                node.graph?.setDirtyCanvas(true, true);
            });
        } else if (node.comfyClass === "Unbundler") {
            attachConnectionSync(node, () => syncNode(node, true));
            addButton(node, "🔄 Sync Keys", () => {
                syncNode(node);
                node.graph?.setDirtyCanvas(true, true);
            });
            // A newly dropped node would otherwise arrive showing the node
            // definition's full bank of MAX_UNBUNDLER_OUTPUTS sockets; start it
            // at one and let it grow to whatever bundle gets connected. Not
            // during a workflow load - there configure() restores the saved
            // sockets and afterConfigureGraph resolves them against the graph.
            if (!app.configuringGraph) applyKeysToUnbundler(node, [], true);
        }
    },
});
