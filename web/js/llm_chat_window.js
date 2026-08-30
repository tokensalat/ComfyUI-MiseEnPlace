// Three levels up, not two: WEB_DIRECTORY is "./web" and these live in
// web/js/, so they are served from /extensions/ComfyUI-MiseEnPlace/js/ .
// "../../scripts/app.js" (what packs whose files sit one level shallower
// use) resolves to /extensions/scripts/app.js, 404s, and silently stops
// the whole module - and therefore the extension - from loading.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const CHAT_NODE_NAME = "LlamaCppChatSession";
const MESSAGES_HEIGHT = 280;
const WIDGET_GAP = 8;

// Base type size for the whole window; every other size is derived from it via
// the --mep-chat-font custom property, so this one number tunes the lot.
const CHAT_FONT_SIZE = 14;

// The composer starts at INPUT_MIN_ROWS and grows with what you type up to
// INPUT_MAX_ROWS, then scrolls. The px figures are shared with the stylesheet
// so the CSS clamp and the JS autosize can't drift apart.
const INPUT_LINE_HEIGHT = 20;
const INPUT_MIN_ROWS = 3;
const INPUT_MAX_ROWS = 8;
const INPUT_CHROME = 14; // 6px padding top + 6px bottom + 1px border each side
const INPUT_MIN_HEIGHT = INPUT_MIN_ROWS * INPUT_LINE_HEIGHT + INPUT_CHROME;
const INPUT_MAX_HEIGHT = INPUT_MAX_ROWS * INPUT_LINE_HEIGHT + INPUT_CHROME;

// Must match STREAM_EVENT in nodes/llm/llama_cpp_chat_session.py. ComfyUI's
// api.js only dispatches a websocket message type that something registered a
// listener for - an unregistered type raises "Unknown message type" instead -
// so the listener is installed once at extension load, below.
const STREAM_EVENT = "miseenplace.chat.delta";

const STATUS_ROW_HEIGHT = 24;
const WIDGET_HEIGHT = MESSAGES_HEIGHT + STATUS_ROW_HEIGHT + INPUT_MIN_HEIGHT + WIDGET_GAP;

function escapeHtml(str) {
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// Small, self-contained markdown-to-HTML renderer covering the common chat
// subset (bold/italic, inline+fenced code, headers, lists, links, quotes,
// paragraphs). Not a full CommonMark implementation. Input is HTML-escaped
// before any tag is introduced, so raw HTML typed by the model can't inject
// markup - only the tags we add ourselves end up live.
function renderMarkdown(text) {
    if (!text) return "";

    const codeBlocks = [];
    let working = text.replace(/```(?:[^\n]*)\n?([\s\S]*?)```/g, (_, code) => {
        const idx = codeBlocks.length;
        codeBlocks.push(code.replace(/\n$/, ""));
        return ` CODEBLOCK${idx} `;
    });

    working = escapeHtml(working);

    working = working.replace(/^###### (.*)$/gm, "<h6>$1</h6>");
    working = working.replace(/^##### (.*)$/gm, "<h5>$1</h5>");
    working = working.replace(/^#### (.*)$/gm, "<h4>$1</h4>");
    working = working.replace(/^### (.*)$/gm, "<h3>$1</h3>");
    working = working.replace(/^## (.*)$/gm, "<h2>$1</h2>");
    working = working.replace(/^# (.*)$/gm, "<h1>$1</h1>");

    working = working.replace(/^&gt; ?(.*)$/gm, "<blockquote>$1</blockquote>");

    working = working.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    working = working.replace(/__(.+?)__/g, "<strong>$1</strong>");
    working = working.replace(/\*(.+?)\*/g, "<em>$1</em>");
    working = working.replace(/(?<!\w)_(.+?)_(?!\w)/g, "<em>$1</em>");

    working = working.replace(/`([^`]+?)`/g, "<code>$1</code>");

    working = working.replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );

    working = working.replace(/(?:^|\n)((?:[-*] .*(?:\n|$))+)/g, (block) => {
        const items = block
            .trim()
            .split("\n")
            .map((line) => `<li>${line.replace(/^[-*] /, "")}</li>`)
            .join("");
        return `\n<ul>${items}</ul>\n`;
    });
    working = working.replace(/(?:^|\n)((?:\d+\. .*(?:\n|$))+)/g, (block) => {
        const items = block
            .trim()
            .split("\n")
            .map((line) => `<li>${line.replace(/^\d+\. /, "")}</li>`)
            .join("");
        return `\n<ol>${items}</ol>\n`;
    });

    working = working
        .split(/\n{2,}/)
        .map((block) => {
            if (/^\s*<(h\d|ul|ol|blockquote)/.test(block.trim())) return block;
            const trimmed = block.trim();
            return trimmed ? `<p>${trimmed.replace(/\n/g, "<br>")}</p>` : "";
        })
        .join("\n");

    working = working.replace(/ CODEBLOCK(\d+) /g, (_, idx) => {
        return `<pre><code>${escapeHtml(codeBlocks[Number(idx)])}</code></pre>`;
    });

    return working;
}

function renderMessage(msg) {
    const role = msg?.role || "assistant";
    const el = document.createElement("div");
    el.className = `miseenplace-chat-msg role-${role}`;

    if (role !== "system") {
        const roleLabel = document.createElement("div");
        roleLabel.className = "miseenplace-chat-role";
        roleLabel.textContent = role === "user" ? "You" : "Assistant";
        el.appendChild(roleLabel);
    }

    const blocks = Array.isArray(msg?.content) ? msg.content : [{ type: "text", text: msg?.content ?? "" }];
    for (const block of blocks) {
        if (block?.type === "image_url") {
            const img = document.createElement("img");
            img.src = block.image_url?.url || "";
            el.appendChild(img);
        } else {
            const textEl = document.createElement("div");
            textEl.className = "miseenplace-chat-text";
            textEl.innerHTML = renderMarkdown(String(block?.text ?? ""));
            el.appendChild(textEl);
        }
    }
    return el;
}

function renderHistory(container, messages) {
    if (!container) return;
    container.innerHTML = "";
    for (const msg of messages || []) {
        container.appendChild(renderMessage(msg));
    }
    container.scrollTop = container.scrollHeight;
}

// Grow the composer to fit what has been typed. The CSS min-height/max-height
// do the clamping, so this only has to ask for the content height; adding
// offsetHeight - clientHeight puts the border back, which scrollHeight omits
// and box-sizing: border-box would otherwise eat.
function autosizeInput(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight + textarea.offsetHeight - textarea.clientHeight}px`;
}

// An optimistic echo of what was just sent, so the message appears the moment
// you hit Enter instead of when the queue gets round to the node. Its pending
// state is spelled out in the role label rather than shown by fading the
// bubble: a slow reply leaves this on screen for the whole generation, and at
// the opacity that reads as "pending" the text drops to ~2.4:1.
function appendPendingMessage(container, text) {
    if (!container) return;
    const el = renderMessage({ role: "user", content: text });
    el.classList.add("pending");
    const roleLabel = el.querySelector(".miseenplace-chat-role");
    if (roleLabel) roleLabel.textContent = "You · sending…";
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
}

// The session id the Python side derives when the widget is left blank
// (LlamaCppChatSession._resolve_session_id).
function resolveSessionId(node) {
    const explicit = node.widgets?.find((w) => w.name === "session_id")?.value;
    const trimmed = typeof explicit === "string" ? explicit.trim() : "";
    return trimmed || `__node_${node.id}`;
}

function formatCount(n) {
    return Number(n ?? 0).toLocaleString();
}

// Anything above these fractions of the context window gets a warning colour,
// since past roughly three quarters full a long reply may not fit.
const METER_WARN = 75;
const METER_DANGER = 90;

function renderStats(node, stats) {
    const view = node._zdChatStatus;
    if (!view) return;
    node._zdChatStats = stats ?? null;
    if (!stats) {
        view.text.textContent = "";
        view.meter.style.display = "none";
        return;
    }

    // "~" is not decoration: the count is only exact at the moment of the last
    // reply. Between turns it is that measurement scaled by character growth.
    const approx = stats.measured ? "~" : "~~";
    const limit = stats.context_size;
    view.text.textContent = limit
        ? `${stats.turns} turns · ${approx}${formatCount(stats.tokens)} / ${formatCount(limit)} tokens (${stats.percent}%)`
        : `${stats.turns} turns · ${approx}${formatCount(stats.tokens)} tokens`;
    view.text.title = stats.measured
        ? `Calibrated from the server's last reported prompt_tokens (${formatCount(stats.last_prompt_tokens)}) over ${formatCount(stats.chars)} characters.`
        : `Rough estimate at ${4} characters per token - run a turn and the server's own token count takes over.`;

    if (limit) {
        const pct = Math.max(0, Math.min(100, stats.percent ?? 0));
        view.meter.style.display = "";
        view.fill.style.width = `${pct}%`;
        view.fill.classList.toggle("warn", pct >= METER_WARN && pct < METER_DANGER);
        view.fill.classList.toggle("danger", pct >= METER_DANGER);
    } else {
        view.meter.style.display = "none";
    }
}

function applyPayload(node, raw) {
    if (!raw) return false;
    try {
        const payload = JSON.parse(raw);
        renderHistory(node._zdChatMessagesEl, payload.messages);
        renderStats(node, payload.stats);
        return true;
    } catch (e) {
        console.warn("[MiseEnPlace Chat] failed to render history", e);
        return false;
    }
}

// A reload leaves app.nodeOutputs empty, but the session lives in the server
// process - so ask it directly.
async function loadStats(node) {
    try {
        const params = new URLSearchParams({ session_id: resolveSessionId(node) });
        const response = await api.fetchApi(`/miseenplace/llm_chat/stats?${params}`);
        if (!response.ok) return;
        const payload = await response.json();
        if (payload.messages?.length) renderHistory(node._zdChatMessagesEl, payload.messages);
        renderStats(node, payload.stats);
    } catch (e) {
        console.warn("[MiseEnPlace Chat] failed to load session stats", e);
    }
}

function notify(detail, severity = "warn") {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary: "LLM Chat", detail, life: 5000 });
    } else {
        console.warn(`[MiseEnPlace Chat] ${detail}`);
    }
}

async function compactSession(node, button) {
    const keepWidget = node.widgets?.find((w) => w.name === "compact_keep_turns");
    const keepTurns = Number.isFinite(keepWidget?.value) ? Math.round(keepWidget.value) : 2;
    const label = button.textContent;
    // Summarising is a full generation on the same server, so it can take a
    // while - make that visible and make a second click impossible.
    button.disabled = true;
    button.textContent = "Compacting…";
    try {
        const response = await api.fetchApi("/miseenplace/llm_chat/compact", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: resolveSessionId(node), keep_turns: keepTurns }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.error) {
            notify(payload.error || `Compaction failed (HTTP ${response.status}).`);
            return;
        }
        renderHistory(node._zdChatMessagesEl, payload.messages);
        renderStats(node, payload.stats);
        // The cached ui payload still holds the pre-compaction history and
        // would come back on the next reload.
        delete app.nodeOutputs?.[String(node.id)];
        notify(
            `Compacted ${payload.compacted} message(s) into a summary, keeping the last ${keepTurns} turn(s).`,
            "success"
        );
    } catch (e) {
        notify(`Compaction failed: ${e}`);
    } finally {
        button.disabled = false;
        button.textContent = label;
    }
}

// The bubble a reply is being streamed into. Rebuilt from scratch when a turn
// starts, and abandoned when onExecuted re-renders the authoritative history.
function beginStreaming(node) {
    const container = node._zdChatMessagesEl;
    if (!container) return null;
    const el = document.createElement("div");
    el.className = "miseenplace-chat-msg role-assistant streaming";
    const role = document.createElement("div");
    role.className = "miseenplace-chat-role";
    role.textContent = "Assistant · typing…";
    const reasoning = document.createElement("div");
    reasoning.className = "miseenplace-chat-reasoning";
    reasoning.style.display = "none";
    const text = document.createElement("div");
    text.className = "miseenplace-chat-text";
    el.append(role, reasoning, text);
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
    return { el, role, reasoning, text, content: "", thinking: "" };
}

function applyDelta(node, detail) {
    const container = node._zdChatMessagesEl;
    if (!container) return;
    let live = node._zdChatStream;
    if (!live || !live.el.isConnected) {
        live = node._zdChatStream = beginStreaming(node);
        if (!live) return;
    }

    // A reasoning model emits its thinking before any answer text; showing it
    // is the difference between visible progress and an apparently frozen node.
    if (detail.reasoning) {
        live.thinking += detail.reasoning;
        live.reasoning.style.display = "";
        live.reasoning.textContent = live.thinking;
    }
    if (detail.content) {
        live.content += detail.content;
    }
    if (detail.done && typeof detail.full_text === "string" && detail.full_text) {
        live.content = detail.full_text;
    }

    // Rendered as plain text while streaming: half-arrived markdown produces
    // flickering broken structure, and the finished turn is re-rendered
    // properly by onExecuted a moment later anyway.
    live.text.textContent = live.content;

    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 48;
    if (atBottom) container.scrollTop = container.scrollHeight;

    if (detail.done) {
        live.role.textContent = "Assistant";
        live.el.classList.remove("streaming");
        node._zdChatStream = null;
    }
}

function findChatNode(nodeId, sessionId) {
    for (const node of app.graph?.nodes ?? app.graph?._nodes ?? []) {
        if (node.type !== CHAT_NODE_NAME) continue;
        if (nodeId != null && String(node.id) === String(nodeId)) return node;
        if (nodeId == null && resolveSessionId(node) === sessionId) return node;
    }
    return null;
}

let stylesInjected = false;
function ensureStyles() {
    if (stylesInjected) return;
    stylesInjected = true;
    const style = document.createElement("style");
    style.textContent = `
        /* Palette is derived from ComfyUI's own theme tokens rather than
           hardcoded: :root defines --fg-color/--bg-color for the light theme
           and .dark-theme flips them, so mixing against those two keeps every
           surface and every piece of text legible in both. The plain value on
           each line above the color-mix() is the fallback for browsers that
           don't support it - a later declaration the browser can't parse is
           simply dropped. */
        .miseenplace-chat-window {
            --mep-chat-font: ${CHAT_FONT_SIZE}px;
            --mep-fg: var(--fg-color, #e6e6e6);
            --mep-bg: var(--bg-color, #202020);
            --mep-accent: #2563eb;
            --mep-accent-hover: #1d4ed8;
            --mep-on-accent: #ffffff;

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

            width: 100%; height: 100%; box-sizing: border-box; padding: 4px 0;
            display: flex; flex-direction: column;
            color: var(--mep-text);
        }
        .miseenplace-chat-messages {
            flex: 1 1 auto;
            min-height: 0;
            overflow-y: auto;
            overflow-x: hidden;
            background: var(--mep-panel);
            border: 1px solid var(--mep-border);
            border-radius: 8px;
            padding: 10px;
            box-sizing: border-box;
            font-family: sans-serif;
            font-size: var(--mep-chat-font);
            line-height: 1.55;
            color: var(--mep-text);
            scrollbar-width: thin;
            scrollbar-color: var(--mep-border) transparent;
        }
        .miseenplace-chat-messages::-webkit-scrollbar { width: 10px; }
        .miseenplace-chat-messages::-webkit-scrollbar-thumb {
            background: var(--mep-border); border-radius: 5px;
            border: 3px solid transparent; background-clip: content-box;
        }
        .miseenplace-chat-msg {
            margin-bottom: 10px;
            padding: 7px 11px;
            border-radius: 12px;
            max-width: 88%;
            width: fit-content;
            word-wrap: break-word;
            overflow-wrap: anywhere;
        }
        /* Squared-off corner on the side each speaker sits, so who said what
           reads from the silhouette and not from colour alone. */
        .miseenplace-chat-msg.role-user {
            background: var(--mep-accent); color: var(--mep-on-accent);
            margin-left: auto; border-bottom-right-radius: 4px;
        }
        .miseenplace-chat-msg.role-assistant {
            background: var(--mep-raised); color: var(--mep-text);
            margin-right: auto; border-bottom-left-radius: 4px;
        }
        .miseenplace-chat-msg.role-system {
            background: transparent; color: var(--mep-text-muted); font-style: italic;
            text-align: center; max-width: 100%; width: auto; margin-bottom: 12px;
        }
        /* A real colour, not opacity: 0.6 on 11px text washed the label out. */
        .miseenplace-chat-role {
            font-size: calc(var(--mep-chat-font) - 3px);
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-bottom: 3px;
            color: var(--mep-text-muted);
        }
        .miseenplace-chat-msg.role-user .miseenplace-chat-role {
            color: var(--mep-on-accent);
        }
        .miseenplace-chat-text p { margin: 0 0 6px 0; }
        .miseenplace-chat-text p:last-child { margin-bottom: 0; }
        .miseenplace-chat-text ul, .miseenplace-chat-text ol { margin: 4px 0; padding-left: 18px; }
        .miseenplace-chat-text pre {
            background: var(--mep-sunken); padding: 8px; border-radius: 6px;
            overflow-x: auto; margin: 6px 0;
        }
        .miseenplace-chat-text code {
            background: var(--mep-sunken); padding: 1px 4px; border-radius: 3px;
            font-family: monospace; font-size: calc(var(--mep-chat-font) - 1px);
        }
        /* The user bubble is a solid accent fill, so the generic surface
           tints would vanish into it - tint the bubble's own colour instead. */
        .miseenplace-chat-msg.role-user pre,
        .miseenplace-chat-msg.role-user code {
            background: rgba(0, 0, 0, 0.22); color: var(--mep-on-accent);
        }
        .miseenplace-chat-text pre code { background: none; padding: 0; }
        .miseenplace-chat-text blockquote {
            border-left: 3px solid var(--mep-border); margin: 4px 0;
            padding-left: 10px; color: var(--mep-text-muted);
        }
        .miseenplace-chat-msg.role-user blockquote {
            border-left-color: rgba(255, 255, 255, 0.45); color: inherit; opacity: 0.9;
        }
        .miseenplace-chat-text a { color: inherit; text-decoration: underline; }
        .miseenplace-chat-msg.role-assistant .miseenplace-chat-text a { color: var(--mep-accent); }
        .miseenplace-chat-msg img { max-width: 100%; max-height: 160px; display: block; margin-top: 4px; border-radius: 6px; }
        /* flex-end keeps the button on the bottom edge as the composer grows. */
        .miseenplace-chat-input-row {
            display: flex; gap: 6px; margin-top: 8px; align-items: flex-end; flex: 0 0 auto;
        }
        .miseenplace-chat-input {
            flex: 1; min-width: 0;
            background: var(--mep-bg);
            border: 1px solid var(--mep-border-strong); border-radius: 8px;
            color: var(--mep-text); padding: 6px 8px; font-size: var(--mep-chat-font);
            font-family: sans-serif; outline: none;
            box-sizing: border-box; resize: none;
            line-height: ${INPUT_LINE_HEIGHT}px;
            min-height: ${INPUT_MIN_HEIGHT}px;
            max-height: ${INPUT_MAX_HEIGHT}px;
            overflow-y: auto;
            transition: border-color 0.12s ease, box-shadow 0.12s ease;
        }
        .miseenplace-chat-input::placeholder { color: var(--mep-text-muted); }
        .miseenplace-chat-input:focus {
            border-color: var(--mep-accent);
            box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.25);
        }
        .miseenplace-chat-send {
            background: var(--mep-accent); border: none; border-radius: 8px;
            color: var(--mep-on-accent); padding: 6px 16px; font-size: var(--mep-chat-font);
            font-weight: 600; cursor: pointer;
            flex-shrink: 0; height: ${INPUT_LINE_HEIGHT + 14}px;
            transition: background 0.12s ease;
        }
        .miseenplace-chat-send:hover { background: var(--mep-accent-hover); }
        .miseenplace-chat-send:active { transform: translateY(1px); }
        /* Marked with a label and a dashed ring rather than by fading:
           opacity 0.55 measured 2.4:1, unreadable for the whole generation. */
        .miseenplace-chat-status {
            display: flex; align-items: center; gap: 8px; flex: 0 0 auto;
            height: ${STATUS_ROW_HEIGHT}px; padding: 0 2px;
            font-family: sans-serif; font-size: calc(var(--mep-chat-font) - 3px);
            color: var(--mep-text-muted);
        }
        .miseenplace-chat-usage { white-space: nowrap; }
        .miseenplace-chat-meter {
            flex: 1 1 auto; min-width: 30px; height: 5px; border-radius: 3px;
            background: var(--mep-sunken); overflow: hidden;
        }
        .miseenplace-chat-meter-fill {
            height: 100%; width: 0%; background: var(--mep-accent);
            border-radius: 3px; transition: width 0.2s ease, background 0.2s ease;
        }
        .miseenplace-chat-meter-fill.warn { background: #b45309; }
        .miseenplace-chat-meter-fill.danger { background: #b91c1c; }
        .miseenplace-chat-compact {
            background: var(--mep-raised); border: 1px solid var(--mep-border-strong);
            border-radius: 6px; color: var(--mep-text); padding: 2px 10px;
            font-size: calc(var(--mep-chat-font) - 3px); cursor: pointer; flex-shrink: 0;
            transition: background 0.12s ease;
        }
        .miseenplace-chat-compact:hover:not(:disabled) { background: var(--mep-sunken); }
        .miseenplace-chat-compact:disabled { cursor: progress; color: var(--mep-text-muted); }
        .miseenplace-chat-reasoning {
            font-size: calc(var(--mep-chat-font) - 2px);
            color: var(--mep-text-muted);
            font-style: italic;
            white-space: pre-wrap;
            max-height: 90px;
            overflow-y: auto;
            margin-bottom: 6px;
            padding-left: 8px;
            border-left: 2px solid var(--mep-border-strong);
        }
        .miseenplace-chat-msg.role-assistant.streaming .miseenplace-chat-text::after {
            content: "▌";
            opacity: 0.6;
            margin-left: 1px;
        }
        .miseenplace-chat-msg.pending {
            outline: 1px dashed var(--mep-on-accent);
            outline-offset: -3px;
        }
    `;
    document.head.appendChild(style);
}

function tryRenderCached(node) {
    const cached = app.nodeOutputs?.[String(node.id)];
    const raw = cached?.history?.[0];
    if (!raw) return;
    try {
        const payload = JSON.parse(raw);
        renderHistory(node._zdChatMessagesEl, payload.messages);
        renderStats(node, payload.stats);
    } catch (e) {
        console.warn("[MiseEnPlace Chat] failed to restore cached history", e);
    }
}

// computeSize() walks every visible widget and asks DOM widgets for their
// layout size (LGraphNode._arrangeWidgets -> DOMWidgetImpl.computeLayoutSize),
// so it already knows how tall this node needs to be. Estimating instead - one
// fixed row height per widget - undercounts badly on this node, whose
// `message` and `system_prompt` multiline widgets are ~200px each, and the
// chat window ends up squeezed into whatever is left.
function reserveNodeHeight(node) {
    const [width, height] = node.computeSize();
    node.setSize([Math.max(node.size[0], width), Math.max(node.size[1], height)]);
}

function buildChatWidget(node) {
    ensureStyles();

    const wrapper = document.createElement("div");
    wrapper.className = "miseenplace-chat-window";

    const messages = document.createElement("div");
    messages.className = "miseenplace-chat-messages";
    messages.addEventListener("wheel", (e) => e.stopPropagation());
    wrapper.appendChild(messages);

    const status = document.createElement("div");
    status.className = "miseenplace-chat-status";
    const usage = document.createElement("span");
    usage.className = "miseenplace-chat-usage";
    const meter = document.createElement("div");
    meter.className = "miseenplace-chat-meter";
    meter.style.display = "none";
    const meterFill = document.createElement("div");
    meterFill.className = "miseenplace-chat-meter-fill";
    meter.appendChild(meterFill);
    const compactBtn = document.createElement("button");
    compactBtn.className = "miseenplace-chat-compact";
    compactBtn.textContent = "Compact";
    compactBtn.title =
        "Summarise the older turns into one message and keep the recent ones verbatim, " +
        "freeing context without losing what was established.";
    compactBtn.addEventListener("click", () => compactSession(node, compactBtn));
    status.append(usage, meter, compactBtn);
    wrapper.appendChild(status);
    node._zdChatStatus = { text: usage, meter, fill: meterFill };

    const inputRow = document.createElement("div");
    inputRow.className = "miseenplace-chat-input-row";
    const textInput = document.createElement("textarea");
    textInput.className = "miseenplace-chat-input";
    textInput.rows = INPUT_MIN_ROWS;
    textInput.placeholder = "Type a message - Enter to send, Shift+Enter for a new line...";
    const sendBtn = document.createElement("button");
    sendBtn.className = "miseenplace-chat-send";
    sendBtn.textContent = "Send";
    inputRow.appendChild(textInput);
    inputRow.appendChild(sendBtn);
    wrapper.appendChild(inputRow);

    const messageWidget = node.widgets?.find((w) => w.name === "message");
    const send = () => {
        const text = textInput.value.trim();
        if (!text) return;
        if (messageWidget) messageWidget.value = text;
        textInput.value = "";
        autosizeInput(textInput);
        // Show the turn straight away rather than after the round trip - the
        // next onExecuted re-renders the whole history from the server and
        // supersedes this bubble (including dropping it again if the request
        // failed and the node rolled the user turn back).
        appendPendingMessage(messages, text);
        app.queuePrompt(0);
    };
    sendBtn.addEventListener("click", send);
    textInput.addEventListener("input", () => autosizeInput(textInput));
    textInput.addEventListener("keydown", (e) => {
        // Otherwise the canvas sees the keystrokes too and fires its shortcuts
        // while you are typing - the frontend's own textarea widgets do this.
        e.stopPropagation();
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    });

    // Only a minimum is declared: _arrangeWidgets spreads the node's spare body
    // height across DOM widgets between their min and max, so leaving the max
    // open lets the chat window grow when the node is resized. Pinning
    // min == max == height froze it at MESSAGES_HEIGHT no matter the node size.
    node.addDOMWidget("chat_history", "div", wrapper, {
        serialize: false,
        getMinHeight: () => WIDGET_HEIGHT,
    });
    node._zdChatMessagesEl = messages;
    node._zdChatInputEl = textInput;

    // The chat input line above replaces it as the way to type a per-turn
    // message, so hide the plain multiline widget to avoid two separate
    // "type your message here" controls on one node. Hide it before sizing:
    // computeSize() skips hidden widgets, and this one is ~200px tall.
    if (messageWidget) {
        messageWidget.hidden = true;
    }

    reserveNodeHeight(node);

    tryRenderCached(node);
    // The cached ui payload predates any compaction done from another tab, and
    // is absent entirely after a reload - the server is the authority.
    loadStats(node);
}

// Registered at module load, before any turn can run: api.js keeps a set of
// message types something has subscribed to and throws on anything else, so a
// late registration would mean the first stream is dropped with an
// "Unknown message type" error.
api.addEventListener(STREAM_EVENT, (event) => {
    const detail = event.detail ?? {};
    const node = findChatNode(detail.node_id, detail.session_id);
    if (node) applyDelta(node, detail);
});

app.registerExtension({
    name: "MiseEnPlace.LlmChatWindow",
    // onExecuted is a real per-node execution callback that ComfyUI's result
    // dispatcher calls directly on the instance, so prototype-level patching
    // here is reliable (unlike onNodeCreated below - see nodeCreated).
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== CHAT_NODE_NAME) return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            applyPayload(this, message?.history?.[0]);
        };
    },
    // Per-instance widget setup belongs here, not in an `onNodeCreated`
    // prototype patch: ComfyUI's node constructor dispatches to extensions'
    // `nodeCreated` hook directly and never calls `this.onNodeCreated?.()`,
    // so a prototype-patched onNodeCreated never runs - which is why the
    // chat window widget wasn't showing up at all.
    async nodeCreated(node) {
        if (node.comfyClass !== CHAT_NODE_NAME) return;
        buildChatWidget(node);
    },
});
