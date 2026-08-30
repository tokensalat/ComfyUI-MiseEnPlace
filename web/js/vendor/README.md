# Vendored browser libraries

Checked in so the nodes render with no internet access. The files are upstream
builds, changed only by:

- stripping the trailing `//# sourceMappingURL=` comment, whose `.map` file is
  not vendored and would 404;
- giving them a `.mjs` extension. ComfyUI auto-imports every `**/*.js` under a
  `WEB_DIRECTORY` as a UI extension (`server.py`), and these are libraries, not
  extensions - `.mjs` keeps them out of that glob while still being served.

| File | Package | Version | License | Source |
| --- | --- | --- | --- | --- |
| `marked.esm.mjs` | [marked](https://github.com/markedjs/marked) | 18.0.10 | MIT | `https://cdn.jsdelivr.net/npm/marked@18.0.10/lib/marked.esm.js` |
| `purify.es.mjs` | [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.14 | Apache-2.0 OR MPL-2.0 | `https://cdn.jsdelivr.net/npm/dompurify@3.4.14/dist/purify.es.mjs` |

Each file keeps its upstream license banner at the top.

Used by `../markdown_viewer.js`: marked turns markdown into HTML, DOMPurify
sanitises it before it reaches the document (the text comes from a model or an
arbitrary upstream node, and marked passes embedded raw HTML through).

To update, re-download at the new version, strip the sourcemap comment, and
edit the table:

```sh
V=18.0.11
curl -sSL -o marked.esm.mjs "https://cdn.jsdelivr.net/npm/marked@$V/lib/marked.esm.js"
sed -i '/sourceMappingURL/d' marked.esm.mjs
```
