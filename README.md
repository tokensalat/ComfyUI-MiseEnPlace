# ComfyUI-MiseEnPlace

A personal collection of custom nodes for ComfyUI, organized by category and
auto-discovered from `nodes/`. Each node registers itself; adding a new one is
just dropping a file into the right subfolder.

## Installation

Clone (or drop) this repository into ComfyUI's `custom_nodes/` directory:

```
cd ComfyUI/custom_nodes
git clone <this-repo-url> ComfyUI-MiseEnPlace
```

Restart ComfyUI. Nodes appear under the `MiseEnPlace/*` categories in the Add
Node menu.

Most nodes only need what ComfyUI already ships with (`torch`, `numpy`,
`Pillow`, `requests`). A few have narrower extras:

- **Jinja Template** needs `jinja2`.
- **LoRA Apply** / **LoRA Auto Apply** use `safetensors` if it's installed, and
  fall back to `torch.load` for `.pt` files if it isn't.
- The **LLM** nodes talk over HTTP to a separately running
  [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` (or any
  OpenAI-compatible chat/completions endpoint) - they don't bundle or run a
  model themselves.

## Nodes

### Bundling

Pack any number of differently-typed values into one `BUNDLE` socket and pull
them back out by name - useful for routing a handful of related values through
a single wire, or overriding a few fields of a bundle without touching the
rest.

- **Bundler** - collects any number of connections of any type into one
  `BUNDLE`. Slots grow automatically as you connect more items.
- **Unbundler** - extracts named values back out of a `BUNDLE` into output
  sockets that take on the type of whatever was bundled.
- **Piercer** - overrides specific values inside a `BUNDLE` by name, adding
  keys that aren't already present.

### Feedback

- **Buffer Read** / **Buffer Write** - a two-node pair that buffers arbitrary
  data across separate queue runs, enabling feedback loops without a graph
  cycle or a file on disk. Both take a plain string `handle` - type the same
  one into each to pair them. Read outputs whatever the matching Write last
  stored (or a `default` the first time); Write's `value` becomes what Read
  outputs on the *next* run.

### Formatting

- **String Formatter** - fills a Python `str.format` template from prefix,
  model, sampler, scheduler, index and runtime fields.
- **Text Concat** - joins any number of text inputs with a configurable
  separator (`\n`/`\t`/`\\` escapes supported), optionally skipping empty
  parts.
- **Jinja Template** - write `{{ name }}` in a template and a matching input
  socket appears on the node automatically; full Jinja (`{% if %}`, `{% for
  %}`, filters) is available, sandboxed.

### Prompting

- **Prompt Builder** - builds a sectioned prompt from a JSON array of
  `add`/`modify`/`delete` operations applied to a standing prompt, and keeps
  every version with a browsable history panel. Emits a JSON Schema for the
  operation document, ready to constrain a model that writes it.

### LLM

Nodes for talking to a llama.cpp-compatible server.

- **Llama-cpp Client** - single-shot chat/completion request: prompt (+
  optional image) in, response out. Supports pattern-based extraction from
  the reply and constraining output to a JSON Schema.
- **Llama-cpp Config** - connection and sampling settings in one place, wired
  into the other two nodes so they share one set of knobs instead of each
  keeping its own copy.
- **Llama-cpp Chat Session** - a persistent, multi-turn chat session (keyed by
  a session id) with a live chat window, token streaming, image attachments,
  history trimming, and a Compact button that summarizes older turns via the
  same server instead of just truncating them.

### LoRA

- **LoRA Loader** - searches configured directories for LoRA files by name,
  auto-pairing `_high`/`_low` variants (for high/low-noise WAN-style setups).
- **LoRA Apply** - loads LoRA weights (safetensors or `.pt`) and merges them
  into provided high/low models.
- **LoRA Auto Apply** - combines the two: discovers a LoRA by name and merges
  it straight into the given models.

### Conditioning

- **Krea2 Gated Rebalance** - reweights a Krea2 conditioning tensor per tap,
  with a smoothstep crossover/overlap to blend the reweighting in gradually
  across taps instead of a hard cutoff.

### Combinators / Selectors / Loopers

Small helpers for sweeping sampler/scheduler combinations across queued runs:

- **List Combinator** - cartesian product of two comma-separated lists into a
  `sampler,scheduler|sampler,scheduler|...` combination string.
- **Sampler & Scheduler Selector** - a single dropdown pair that also emits
  its choice as plain strings.
- **Sampler/Scheduler Looper** - steps through a combination string by index,
  for driving a sweep one queued run at a time.

### Timing

- **Timer Start** / **Timer Stop** - pass a value through while timestamping
  it, then report the elapsed time between the two - useful for timing a
  section of a workflow without leaving the data path.

### Display

- **Markdown Viewer** - renders markdown in the node and keeps a running,
  append-able history (keyed by an id) across queue runs, emitting the whole
  accumulated document as a string so it can be piped onward.

## License

MIT - see [LICENSE](LICENSE).
