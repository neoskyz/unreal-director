# Shipping a UE Wasm build on itch.io

## What only a human can do (once)

itch.io has no API to create a game page, and butler can only push to a page that exists.

1. Create the project, **Kind of project: HTML**.
2. **Embed options: tick "SharedArrayBuffer support".** UE Wasm runs threads, which need `SharedArrayBuffer`, which
   needs a cross-origin isolated page. Without the tick the game stops at "The page is not cross-origin isolated".
3. Keep it **Draft** while testing; after the first push, mark the upload "This file will be played in the browser".
4. `butler login` once (or provide `BUTLER_API_KEY`).

## What the agent does every time

```bash
python3 scripts/build/prepare_web_upload.py Builds/MyGame_Wasm_Shipping/Wasm --patch-sw --zip dist/MyGame_web.zip
ITCH_TARGET=<user>/<game>:html5 scripts/build/itch_push.sh Builds/MyGame_Wasm_Shipping/Wasm
```

`itch_push.sh` is `butler push <stage> <target> --ignore '*.br'`.

## The service-worker header that breaks itch (found on deadline day)

With `bInjectIsolationHeaders=True`, the staged `sw.js` makes the page cross-origin isolated by rewriting responses:
its `isolated()` function adds COOP, COEP and **CORP** to the game page's own navigation response. The engine
template (UE 5.9) sets that CORP to `same-origin`:

```js
// Engine/Platforms/Wasm/Build/Template/sw.js, function isolated(response, request)
h.set('Cross-Origin-Opener-Policy', 'same-origin');
h.set('Cross-Origin-Embedder-Policy', 'require-corp');
h.set('Cross-Origin-Resource-Policy', 'same-origin');   // <- the problem
```

On a normal host that is fine. On itch.io the game is an `<iframe>` served from a different origin than the page
around it, and with "SharedArrayBuffer support" ticked that parent page requires CORP of everything it embeds. A
navigation response marked `same-origin` may not be embedded by a cross-origin parent, so the game's frame is
blocked once the service worker is in control. The fix is one word:

```js
h.set('Cross-Origin-Resource-Policy', 'cross-origin');  // the page may be embedded in a cross-origin iframe (itch.io)
```

Patch the engine template once (every later package carries it), or patch the staged copy with
`prepare_web_upload.py --patch-sw`. `sw.js` is not hashed in the manifest, so patching after staging is safe; the
`sw.js.br` twin goes stale, which does not matter when `.br` files are not uploaded.

Note: `scripts/web/isolation_test_web.py` does not catch this (it tests a top-level page on a plain server). Test the
real thing on a Draft itch page.

## Other notes

- The engine's `_headers` file (for Cloudflare Pages style hosts) also says CORP `same-origin` for every file; if you
  embed the game cross-origin on such a host, change it there too.
- Keys pressed on the page cover can leak into the game once it starts (the cover's handler calls
  `preventDefault`, the engine listens anyway). Starseal removed "Enter = launch" for that reason.
- Make the zip with `index.html` at its top level (jam rule), without `.br` files: `--zip` does that.
