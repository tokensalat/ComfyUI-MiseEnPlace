import base64
import hashlib
import io
import json
import threading
import time

import numpy as np
import requests
from PIL import Image

from comfy_execution.graph_utils import ExecutionBlocker

from ..bundling._bundle_type import Bundle
from ._llm_config import CONFIG_INPUT, field, merge_settings
from ._llm_text import extract_from_reply, extract_pattern_input

# session_id -> list of OpenAI-style chat messages ({"role": ..., "content": ...}).
# Lives for as long as the ComfyUI server process does, which is what gives
# this node its "chat session" behavior across separate queue runs.
_SESSIONS_LOCK = threading.Lock()
_SESSIONS = {}

# session_id -> record of the last turn that actually reached the server:
#   fingerprint  - backs the "don't re-generate just because an attachment
#                  changed" gate below; see _fingerprint()
#   result       - the outputs to reuse when that gate trips
#   settings     - the resolved url/sampling settings, so /compact can talk to
#                  the same server without the frontend having to resolve a
#                  connected LLM_CONFIG itself
#   usage, chars - the server's reported prompt_tokens and the character count
#                  that produced it, which calibrates the token estimate
_LAST_TURN_LOCK = threading.Lock()
_LAST_TURN = {}

# Server base url -> per-slot context window, from llama.cpp's /props. Fetched
# once per server; None means "asked and could not tell".
_CONTEXT_SIZE_LOCK = threading.Lock()
_CONTEXT_SIZE_CACHE = {}

# Marks a message this node wrote when compacting, so a second compaction
# re-summarises the earlier summary instead of stacking them up forever.
SUMMARY_PREFIX = "[Compacted summary of earlier turns]"

# What to do on a turn the gate decides not to generate.
UNCHANGED_BLOCK = "block downstream"
UNCHANGED_REUSE = "reuse last reply"
UNCHANGED_CHOICES = [UNCHANGED_BLOCK, UNCHANGED_REUSE]

# Fallback when the server hasn't reported usage yet. Deliberately crude - it
# is only used until the first real prompt_tokens arrives and calibrates it.
FALLBACK_CHARS_PER_TOKEN = 4.0

# Websocket event the chat window listens for. ComfyUI's frontend throws on a
# message type nothing has registered (api.js dispatches unknown types only if
# addEventListener was called for them), so the extension must register this
# before any turn runs.
STREAM_EVENT = "miseenplace.chat.delta"

# Tokens arrive far faster than a canvas needs repainting; batching them into
# ~12 pushes a second keeps the websocket quiet without looking choppy.
STREAM_FLUSH_SECONDS = 0.08


def _push(event, data):
    """Fire a websocket message from the execution thread.

    send_sync hands the message to the event loop via call_soon_threadsafe, so
    this is safe to call from a node; a missing server just means no live view.
    """
    try:
        from server import PromptServer

        instance = getattr(PromptServer, "instance", None)
        if instance is None:
            return
        instance.send_sync(event, data, instance.client_id)
    except Exception as e:
        print(f"[LlamaCppChatSession] could not push {event}: {e}")


class _DeltaEmitter:
    """Coalesces streamed fragments into periodic websocket pushes."""

    def __init__(self, sid, node_id):
        self.sid = sid
        self.node_id = node_id
        self.pending_content = []
        self.pending_reasoning = []
        self.last_flush = 0.0

    def add(self, text, is_reasoning):
        (self.pending_reasoning if is_reasoning else self.pending_content).append(text)
        if time.monotonic() - self.last_flush >= STREAM_FLUSH_SECONDS:
            self.flush()

    def flush(self, done=False, full_text=None):
        content = "".join(self.pending_content)
        reasoning = "".join(self.pending_reasoning)
        if not (content or reasoning or done):
            return
        self.pending_content.clear()
        self.pending_reasoning.clear()
        self.last_flush = time.monotonic()
        payload = {
            "session_id": self.sid,
            "node_id": str(self.node_id) if self.node_id is not None else None,
            "content": content,
            "reasoning": reasoning,
            "done": done,
        }
        # The final push carries the whole reply, so the live view can't end up
        # out of step with what actually got stored.
        if done and full_text is not None:
            payload["full_text"] = full_text
        _push(STREAM_EVENT, payload)


def stream_chat(url, payload, timeout, emitter):
    """Run one streaming completion, feeding fragments to `emitter`.

    llama.cpp speaks the OpenAI SSE dialect: `data: {json}` lines ending with
    `data: [DONE]`. Reasoning models put their thinking in delta.reasoning_content
    and the answer in delta.content, and only the latter is the reply - but the
    former is streamed to the UI too, or a long thinking phase looks like a hang.
    Returns (content, reasoning, usage, finish_reason).
    """
    request = dict(payload, stream=True, stream_options={"include_usage": True})
    content_parts = []
    reasoning_parts = []
    usage = None
    finish_reason = None

    with requests.post(
        url,
        json=request,
        headers={"Content-Type": "application/json"},
        timeout=timeout,
        stream=True,
    ) as response:
        # requests falls back to ISO-8859-1 for any text/* content-type that
        # carries no charset, and llama.cpp's stream is text/event-stream - so
        # without this every non-ASCII character comes through mojibaked
        # (U+2019 arrives as "â€™", which renders as a stray "a" with a hat).
        # SSE is UTF-8 by definition, so say so before reading: decode_unicode
        # then runs an incremental UTF-8 decoder, and multi-byte characters
        # survive being split across chunk boundaries.
        response.encoding = "utf-8"
        if response.status_code != 200:
            raise RuntimeError(f"Server returned error status {response.status_code}: {response.text[:500]}")
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            body = line[len("data:") :].strip()
            if body == "[DONE]":
                break
            try:
                chunk = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                text = delta.get("content")
                thinking = delta.get("reasoning_content")
                if text:
                    content_parts.append(text)
                    emitter.add(text, False)
                if thinking:
                    reasoning_parts.append(thinking)
                    emitter.add(thinking, True)
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

    return "".join(content_parts), "".join(reasoning_parts), usage, finish_reason



def message_text(message):
    """The textual part of a message, with image blocks noted but not inlined.

    Content is either a plain string or the OpenAI block list used when images
    are attached; base64 image payloads are enormous and must never reach a
    character count or a summarisation transcript.
    """
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image_url":
            parts.append("[image]")
        elif block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts)


def history_chars(history):
    return sum(len(message_text(m)) for m in history)


def server_base(url):
    """The llama.cpp server root, given any of its endpoint urls."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url or "")
    path = parts.path
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1/completions", "/completions"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))


def context_size(url, timeout=5):
    """Per-slot context window from llama.cpp's /props, cached per server.

    None when the server can't be reached or doesn't report it - callers show
    a raw token count instead of a percentage in that case.
    """
    base = server_base(url)
    if not base:
        return None
    with _CONTEXT_SIZE_LOCK:
        if base in _CONTEXT_SIZE_CACHE:
            return _CONTEXT_SIZE_CACHE[base]
    value = None
    try:
        response = requests.get(f"{base}/props", timeout=timeout)
        if response.status_code == 200:
            props = response.json()
            generation = props.get("default_generation_settings") or {}
            for candidate in (
                generation.get("n_ctx"),
                (generation.get("params") or {}).get("n_ctx"),
                props.get("n_ctx"),
            ):
                if isinstance(candidate, int) and candidate > 0:
                    value = candidate
                    break
    except Exception as e:
        print(f"[LlamaCppChatSession] could not read context size from {base}/props: {e}")
    with _CONTEXT_SIZE_LOCK:
        _CONTEXT_SIZE_CACHE[base] = value
    return value


def context_stats(sid, history=None):
    """What the session currently costs, for the node's status bar.

    Anchored on the server's own prompt_tokens from the last turn: dividing
    that by the character count that produced it gives a tokens-per-character
    ratio for this actual model and conversation, which beats a fixed divisor.
    Before the first reply there is nothing to calibrate against, so it falls
    back to FALLBACK_CHARS_PER_TOKEN and says so.
    """
    if history is None:
        with _SESSIONS_LOCK:
            history = list(_SESSIONS.get(sid, []))
    with _LAST_TURN_LOCK:
        entry = dict(_LAST_TURN.get(sid) or {})

    chars = history_chars(history)
    prompt_tokens = (entry.get("usage") or {}).get("prompt_tokens")
    measured_chars = entry.get("chars") or 0
    if isinstance(prompt_tokens, int) and prompt_tokens > 0 and measured_chars > 0:
        tokens = int(round(chars * (prompt_tokens / measured_chars)))
        measured = True
    else:
        tokens = int(round(chars / FALLBACK_CHARS_PER_TOKEN))
        measured = False

    limit = context_size((entry.get("settings") or {}).get("url", "")) if entry else None
    return {
        "messages": len(history),
        "turns": len([m for m in history if m.get("role") == "user"]),
        "chars": chars,
        "tokens": tokens,
        "measured": measured,
        "last_prompt_tokens": prompt_tokens,
        "context_size": limit,
        "percent": round(100.0 * tokens / limit, 1) if limit else None,
    }


class LlamaCppChatSession:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "url": field("url"),
                "message": ("STRING", {"default": "", "multiline": True}),
                "session_id": (
                    "STRING",
                    {"default": "", "tooltip": "Leave blank to use a session unique to this node."},
                ),
                "reset_session": ("BOOLEAN", {"default": False}),
                "max_history_turns": (
                    "INT",
                    {"default": 20, "min": 0, "max": 1000, "tooltip": "0 = unlimited. Oldest turns are dropped first; the system prompt is always kept."},
                ),
                "extract_pattern": extract_pattern_input(),
                "timeout": field("timeout"),
                "temperature": field("temperature"),
                "repeat_penalty": field("repeat_penalty"),
                "top_k": field("top_k"),
                "top_p": field("top_p"),
                "min_p": field("min_p"),
                "presence_penalty": field("presence_penalty"),
                "min_image_tokens": field("min_image_tokens"),
                "max_image_tokens": field("max_image_tokens"),
                "do_image_splitting": field("do_image_splitting"),
                "seed": field("seed"),
                "force_resend": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                # A link-only socket (like 'config' below), so it takes no
                # widgets_values slot and cannot shift saved values. Connect a
                # Bundler here to attach arbitrary extra content to the user
                # turn: image-shaped items become image attachments the same
                # way the old dedicated 'images' input did, and everything
                # else is stringified into its own labelled text note - see
                # _attachment_blocks().
                "attachments": (
                    Bundle.io_type,
                    {
                        "tooltip": "Optional. Connect a Bundler's output to attach arbitrary extra content to the user turn - image-shaped items are sent as image attachments, everything else is stringified into a note labelled with its bundle key.",
                    },
                ),
                "system_prompt": ("STRING", {"default": "", "multiline": True}),
                "config": CONFIG_INPUT,
                "when_unchanged": (
                    UNCHANGED_CHOICES,
                    {
                        "default": UNCHANGED_BLOCK,
                        "tooltip": "What happens on a run where nothing but the attachments changed. 'block downstream' emits nothing, so the rest of the graph does not run. 'reuse last reply' emits the previous reply and lets the chain continue.",
                    },
                ),
                "stream": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Show the reply arriving token by token in the chat window. The outputs are identical either way - this only affects the live view.",
                    },
                ),
                "compact_keep_turns": (
                    "INT",
                    {
                        "default": 2,
                        "min": 0,
                        "max": 50,
                        "tooltip": "How many recent exchanges the Compact button keeps verbatim. Everything older is replaced by one summary the model writes.",
                    },
                ),
                # Deliberately last: widgets_values is saved positionally and
                # remapped positionally on load (migrateWidgetsValues only
                # drops forceInput slots, it does not match by name), so a new
                # widget anywhere but the end would shift every saved value
                # after it.
                "resend_on_attachment_change": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "Off: a new turn is only generated when a prompt or setting changes - swapping what's connected to 'attachments' on its own reuses the last reply. On: a change to the attachments generates too (for workflows that iterate over images or other attached values with a fixed prompt).",
                    },
                ),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("full_text", "extracted", "session_id", "debug")
    FUNCTION = "run"
    CATEGORY = "MiseEnPlace/LLM"

    @classmethod
    def IS_CHANGED(s, **kwargs):
        if kwargs.get("force_resend", False):
            return float(time.time())
        return ""

    @staticmethod
    def _resolve_session_id(session_id, unique_id):
        session_id = (session_id or "").strip()
        if session_id:
            return session_id
        return f"__node_{unique_id}"

    @staticmethod
    def _images_to_content_blocks(images):
        blocks = []
        if images is None:
            return blocks
        try:
            arr = images if isinstance(images, np.ndarray) else images.cpu().numpy()
        except Exception as e:
            print(f"Error reading images tensor: {e}")
            return blocks

        if arr.ndim == 3:
            arr = arr[None, ...]

        for i in range(arr.shape[0]):
            frame = arr[i]
            if frame.dtype in (np.float32, np.float64):
                frame = (frame * 255).clip(0, 255).astype(np.uint8)
            try:
                pil_image = Image.fromarray(frame)
                buffered = io.BytesIO()
                pil_image.save(buffered, format="PNG")
                img_b64 = base64.b64encode(buffered.getvalue()).decode()
                blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    }
                )
            except Exception as e:
                print(f"Error converting image {i} to base64: {e}")
        return blocks

    @staticmethod
    def _looks_like_image(value):
        """Whether an arbitrary bundle value is an IMAGE-shaped tensor.

        Bundler carries values through untyped, so an attachment could be
        anything; only something that actually reshapes into (frames, h, w,
        channels) should be sent as an image_url block instead of text.
        """
        try:
            arr = value if isinstance(value, np.ndarray) else value.cpu().numpy()
        except Exception:
            return False
        return isinstance(arr, np.ndarray) and arr.ndim in (3, 4)

    @classmethod
    def _attachment_blocks(cls, attachments):
        """Bundle items -> extra content blocks for the user turn.

        Each item becomes its own block, in the bundle's key order: an
        image-shaped value becomes image_url block(s) the same way the old
        dedicated 'images' input did, and anything else is stringified into
        its own text block labelled with its bundle key, so several
        attachments stay distinguishable in the transcript instead of being
        silently concatenated together.
        """
        blocks = []
        if not attachments:
            return blocks
        for key, value in attachments.items():
            if value is None:
                continue
            if cls._looks_like_image(value):
                blocks.extend(cls._images_to_content_blocks(value))
            else:
                blocks.append({"type": "text", "text": f"{key}: {value}"})
        return blocks

    @staticmethod
    def _fingerprint(inputs):
        """Hash of everything that should justify a new generation.

        ComfyUI's own cache can't express "ignore this one input": a node's
        signature folds in the full signature of every ancestor
        (CacheKeySetInputSignature.get_node_signature), and IS_CHANGED only
        ever adds to that - so re-touching an upstream node feeding
        'attachments' always re-runs this node. The gate therefore lives here
        instead: the node executes, compares this fingerprint against the
        last turn it actually sent, and reuses that reply if nothing but the
        attachments moved.
        """
        payload = {k: v for k, v in inputs.items() if k != "attachments"}
        blob = json.dumps(payload, sort_keys=True, default=repr)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _ui_payload(sid):
        with _SESSIONS_LOCK:
            history = list(_SESSIONS.get(sid, []))
        return {
            "history": [
                json.dumps(
                    {"session_id": sid, "messages": history, "stats": context_stats(sid, history)}
                )
            ]
        }

    @staticmethod
    def _trim_history(history, max_turns):
        if max_turns <= 0:
            return history
        system_msgs = [m for m in history if m.get("role") == "system"]
        rest = [m for m in history if m.get("role") != "system"]
        max_messages = max_turns * 2  # one user + one assistant message per turn
        if len(rest) > max_messages:
            rest = rest[-max_messages:]
        return system_msgs + rest

    def run(
        self,
        url,
        message,
        session_id,
        reset_session,
        max_history_turns,
        extract_pattern,
        timeout,
        temperature,
        repeat_penalty,
        top_k,
        top_p,
        min_p,
        presence_penalty,
        min_image_tokens,
        max_image_tokens,
        do_image_splitting,
        seed,
        force_resend,
        attachments=None,
        system_prompt="",
        config=None,
        when_unchanged=UNCHANGED_BLOCK,
        stream=True,
        compact_keep_turns=2,  # read by the Compact button, not by run()
        resend_on_attachment_change=False,
        unique_id=None,
    ):
        sid = self._resolve_session_id(session_id, unique_id)

        # A connected Llama-cpp Config overrides the widgets it covers; with
        # nothing connected this is just the local values. Prompts are never
        # part of it - see nodes/llm/_llm_config.py.
        settings = merge_settings(
            config,
            {
                "url": url,
                "timeout": timeout,
                "temperature": temperature,
                "repeat_penalty": repeat_penalty,
                "top_k": top_k,
                "top_p": top_p,
                "min_p": min_p,
                "presence_penalty": presence_penalty,
                "min_image_tokens": min_image_tokens,
                "max_image_tokens": max_image_tokens,
                "do_image_splitting": do_image_splitting,
                "seed": seed,
            },
        )
        url = settings["url"]
        timeout = settings["timeout"]
        seed = settings["seed"]

        # Fingerprinted from the *resolved* settings, so turning a knob on the
        # shared config node counts as a change here too - see _fingerprint().
        # Only whether something is attached is hashed, never its content:
        # the bundle can carry arbitrary (and arbitrarily large) values, so
        # dumping it would be slow and, for non-JSON-able values, would fall
        # back to a repr() that can silently miss real changes anyway.
        fingerprint_fields = dict(
            settings,
            message=message,
            session_id=sid,
            max_history_turns=max_history_turns,
            extract_pattern=extract_pattern,
            system_prompt=system_prompt,
            has_attachments=attachments is not None,
        )
        fingerprint = self._fingerprint(fingerprint_fields)

        # force_resend and reset_session are explicit "do it anyway" switches,
        # so they bypass the gate rather than feeding it.
        if not (force_resend or reset_session or resend_on_attachment_change):
            with _LAST_TURN_LOCK:
                last = _LAST_TURN.get(sid)
            # .get, not [...]: compaction clears the fingerprint while leaving
            # the rest of the record (settings, usage) in place.
            if last and last.get("fingerprint") == fingerprint:
                if when_unchanged == UNCHANGED_BLOCK:
                    # Returning the previous reply would still set the whole
                    # downstream chain running, because ComfyUI caches on input
                    # signature rather than output value - an upstream
                    # attachment swap re-runs every consumer regardless of the
                    # text being identical. An ExecutionBlocker is the only
                    # thing that actually stops that propagation.
                    print(
                        f"[LlamaCppChatSession:{sid}] inputs unchanged apart from the attachments; "
                        "blocking downstream execution"
                    )
                    blocked = tuple(ExecutionBlocker(None) for _ in self.RETURN_TYPES)
                    return {"ui": self._ui_payload(sid), "result": blocked}
                print(
                    f"[LlamaCppChatSession:{sid}] inputs unchanged apart from the attachments; "
                    "reusing the last reply instead of generating"
                )
                return {"ui": self._ui_payload(sid), "result": last["result"]}

        if reset_session:
            with _LAST_TURN_LOCK:
                _LAST_TURN.pop(sid, None)

        with _SESSIONS_LOCK:
            if reset_session:
                _SESSIONS.pop(sid, None)
            history = _SESSIONS.setdefault(sid, [])

            system_prompt = (system_prompt or "").strip()
            if system_prompt:
                if history and history[0].get("role") == "system":
                    history[0]["content"] = system_prompt
                else:
                    history.insert(0, {"role": "system", "content": system_prompt})

            content_blocks = self._attachment_blocks(attachments)
            if content_blocks:
                user_message = {
                    "role": "user",
                    "content": [{"type": "text", "text": message}] + content_blocks,
                }
            else:
                user_message = {"role": "user", "content": message}
            history.append(user_message)

            payload_messages = list(history)

        payload = {
            "messages": payload_messages,
            "temperature": settings["temperature"],
            "repeat_penalty": settings["repeat_penalty"],
            "top_k": settings["top_k"],
            "top_p": settings["top_p"],
            "min_p": settings["min_p"],
            "presence_penalty": settings["presence_penalty"],
            "min_image_tokens": settings["min_image_tokens"],
            "max_image_tokens": settings["max_image_tokens"],
            "do_image_splitting": settings["do_image_splitting"],
            "stream": False,
        }
        if seed != -1:
            payload["seed"] = seed

        def rollback_user_turn():
            with _SESSIONS_LOCK:
                current = _SESSIONS.get(sid)
                if current and current[-1] is user_message:
                    current.pop()

        try:
            headers = {"Content-Type": "application/json"}
            print(
                f"[LlamaCppChatSession:{sid}] sending turn "
                f"({len(payload_messages)} messages in history) to {url}"
                f"{' (streaming)' if stream else ''}"
            )

            usage = None
            if stream:
                generated_text = ""
                reasoning = ""
                finish_reason = None
                # No opening push: the window already shows the optimistic
                # "sending…" bubble, and the live one appears on the first
                # fragment - which for a reasoning model is its thinking.
                emitter = _DeltaEmitter(sid, unique_id)
                try:
                    generated_text, reasoning, usage, finish_reason = stream_chat(
                        url, payload, timeout, emitter
                    )
                finally:
                    # Always close the live bubble, including on failure, or the
                    # window keeps showing a half-written reply as if it were live.
                    emitter.flush(done=True, full_text=generated_text)
                result = {
                    "streamed": True,
                    "finish_reason": finish_reason,
                    "usage": usage,
                    "reasoning_chars": len(reasoning),
                }
                debug_output = json.dumps(result, indent=2)
            else:
                response = requests.post(url, json=payload, headers=headers, timeout=timeout)

                if response.status_code != 200:
                    error_msg = f"Server returned error status {response.status_code}: {response.text}"
                    print(error_msg)
                    rollback_user_turn()
                    return {"ui": self._ui_payload(sid), "result": (error_msg, "", sid, error_msg)}

                result = response.json()
                debug_output = json.dumps(result, indent=2)
                usage = result.get("usage") if isinstance(result, dict) else None

                generated_text = ""
                if "choices" in result and len(result["choices"]) > 0:
                    choice = result["choices"][0]
                    if "message" in choice and "content" in choice["message"]:
                        generated_text = choice["message"]["content"]
                    elif "text" in choice:
                        generated_text = choice["text"]
                elif "content" in result:
                    generated_text = result["content"]
                elif "response" in result:
                    generated_text = result["response"]
                elif "text" in result:
                    generated_text = result["text"]
                else:
                    generated_text = debug_output

            with _SESSIONS_LOCK:
                current = _SESSIONS.setdefault(sid, [])
                current.append({"role": "assistant", "content": generated_text})
                _SESSIONS[sid] = self._trim_history(current, max_history_turns)

            extracted = extract_from_reply(
                generated_text, extract_pattern, f"[LlamaCppChatSession:{sid}] "
            )

            print(f"[LlamaCppChatSession:{sid}] received reply: {len(generated_text)} chars")
            turn_result = (generated_text, extracted, sid, debug_output)
            # Recorded only on success, so a failed turn is retried rather
            # than having its error text pinned as "the last reply". The usage
            # and the prompt's character count are what calibrate the token
            # estimate in context_stats(); settings let /compact reach the
            # same server later.
            with _LAST_TURN_LOCK:
                _LAST_TURN[sid] = {
                    "fingerprint": fingerprint,
                    "result": turn_result,
                    "settings": dict(settings),
                    "usage": usage if isinstance(usage, dict) else None,
                    "chars": history_chars(payload_messages),
                }
            return {"ui": self._ui_payload(sid), "result": turn_result}

        except requests.exceptions.RequestException as e:
            error_msg = f"HTTP request failed: {str(e)}"
            print(error_msg)
            rollback_user_turn()
            return {"ui": self._ui_payload(sid), "result": (error_msg, "", sid, error_msg)}
        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse JSON response: {str(e)}"
            print(error_msg)
            rollback_user_turn()
            return {"ui": self._ui_payload(sid), "result": (error_msg, "", sid, error_msg)}
        except Exception as e:
            error_msg = f"Error communicating with llama-cpp server: {str(e)}"
            print(error_msg)
            rollback_user_turn()
            return {"ui": self._ui_payload(sid), "result": (error_msg, "", sid, error_msg)}


COMPACT_SYSTEM_PROMPT = (
    "You compact conversation transcripts so a chat can continue past its context limit. "
    "Rewrite the transcript below as a dense third-person summary. Keep every decision, "
    "constraint, fact, name, and piece of state that later turns would need; keep the user's "
    "stated goal and anything still unresolved. Drop pleasantries and restatements. Do not "
    "add commentary and do not address the user - output only the summary."
)


def _render_transcript(messages):
    labels = {"user": "User", "assistant": "Assistant", "system": "System"}
    lines = []
    for message in messages:
        text = message_text(message).strip()
        if text:
            lines.append(f"{labels.get(message.get('role'), 'Other')}: {text}")
    return "\n\n".join(lines)


def compact_session(sid, keep_turns=2):
    """Replace all but the last `keep_turns` exchanges with one summary.

    This is a real compaction rather than the truncation max_history_turns
    already does: the dropped turns are summarised by the same server first,
    so what they established survives. Blocking - callers run it off the event
    loop.
    """
    with _LAST_TURN_LOCK:
        entry = dict(_LAST_TURN.get(sid) or {})
    settings = entry.get("settings")
    if not settings:
        return {"error": "This session hasn't run yet, so there is no server to summarise with."}

    with _SESSIONS_LOCK:
        history = list(_SESSIONS.get(sid, []))
    if not history:
        return {"error": "Nothing to compact - this session has no history."}

    def is_summary(message):
        return message.get("role") == "system" and str(message.get("content", "")).startswith(
            SUMMARY_PREFIX
        )

    # A previous summary is folded back in rather than kept alongside the new
    # one, otherwise repeated compactions just accumulate summaries.
    preamble = [m for m in history if m.get("role") == "system" and not is_summary(m)]
    prior = [m for m in history if is_summary(m)]
    exchanges = [m for m in history if m.get("role") != "system"]

    keep_count = max(0, keep_turns) * 2
    keep = exchanges[-keep_count:] if keep_count else []
    dropped = exchanges[: len(exchanges) - len(keep)]
    # Gate on real exchanges being dropped, not on `older` being non-empty:
    # a prior summary alone would otherwise make this re-summarise the summary,
    # which costs a generation and loses detail for no gain.
    if not dropped:
        return {"error": f"Nothing to compact - the last {keep_turns} turn(s) are all there is."}
    older = prior + dropped

    transcript = _render_transcript(older)
    payload = {
        "messages": [
            {"role": "system", "content": COMPACT_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        # A summary should follow the transcript, not improvise on it.
        "temperature": 0.3,
        "top_p": settings.get("top_p", 0.95),
        "min_p": settings.get("min_p", 0.05),
        "stream": False,
    }
    try:
        response = requests.post(
            settings["url"],
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=settings.get("timeout", 300),
        )
        if response.status_code != 200:
            return {"error": f"Server returned {response.status_code}: {response.text[:300]}"}
        body = response.json()
        summary = ""
        choices = body.get("choices") or []
        if choices:
            summary = (choices[0].get("message") or {}).get("content") or choices[0].get("text") or ""
        summary = summary.strip()
        if not summary:
            return {"error": "The server returned an empty summary; history left untouched."}
    except Exception as e:
        return {"error": f"Summarisation request failed: {e}"}

    compacted = (
        preamble + [{"role": "system", "content": f"{SUMMARY_PREFIX}\n\n{summary}"}] + keep
    )
    with _SESSIONS_LOCK:
        _SESSIONS[sid] = compacted
    # The fingerprint gate keys off inputs, not history - drop it so the next
    # run actually regenerates against the compacted context.
    with _LAST_TURN_LOCK:
        if sid in _LAST_TURN:
            _LAST_TURN[sid].pop("fingerprint", None)

    print(
        f"[LlamaCppChatSession:{sid}] compacted {len(older)} message(s) into a summary; "
        f"{len(compacted)} remain"
    )
    return {
        "session_id": sid,
        "messages": compacted,
        "stats": context_stats(sid, compacted),
        "compacted": len(older),
    }


def _register_routes():
    try:
        import asyncio

        from aiohttp import web
        from server import PromptServer
    except Exception as e:  # pragma: no cover - only outside ComfyUI
        print(f"[LlamaCppChatSession] routes not registered ({e}); the node still works, "
              "but the context readout and Compact button will be unavailable.")
        return

    routes = getattr(getattr(PromptServer, "instance", None), "routes", None)
    if routes is None:
        print("[LlamaCppChatSession] PromptServer not ready; routes not registered.")
        return

    @routes.get("/miseenplace/llm_chat/stats")
    async def get_stats(request):
        sid = request.query.get("session_id", "")
        if not sid:
            return web.json_response({"error": "session_id is required"}, status=400)
        with _SESSIONS_LOCK:
            history = list(_SESSIONS.get(sid, []))
        return web.json_response(
            {"session_id": sid, "messages": history, "stats": context_stats(sid, history)}
        )

    @routes.post("/miseenplace/llm_chat/compact")
    async def post_compact(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        sid = (body or {}).get("session_id", "")
        if not sid:
            return web.json_response({"error": "session_id is required"}, status=400)
        keep = (body or {}).get("keep_turns", 2)
        keep = keep if isinstance(keep, int) and keep >= 0 else 2
        # Summarising is a full generation - keep it off the server's event
        # loop or the whole ComfyUI UI stalls for its duration.
        result = await asyncio.to_thread(compact_session, sid, keep)
        return web.json_response(result, status=400 if "error" in result else 200)


_register_routes()


NODE_CLASS_MAPPINGS = {"LlamaCppChatSession": LlamaCppChatSession}

NODE_DISPLAY_NAME_MAPPINGS = {"LlamaCppChatSession": "Llama-cpp Chat Session"}
