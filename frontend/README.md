# Recovery inspector

A local React + TypeScript interface to the actual Rebound journal. The interface
has no seeded dashboard values: it lists persisted runs, dispatch attempts,
evidence, decisions, and tool outcomes returned by the Python service.

## Build and serve

Requires Node.js 22.12+ and pnpm 11.25.0. From the repository root, install the
Python package first as described in the main README, then:

```sh
cd frontend
corepack pnpm install --frozen-lockfile
corepack pnpm build
cd ..
rebound serve --data .rebound --port 8787
```

Open <http://127.0.0.1:8787>. The Vite build writes files to
`src/rebound/static/`; build this directory before creating the Python wheel to
include the inspector. Without generated assets, `/` explains how to build them
and the API remains available at `/docs`.

## Development

Keep `rebound serve` running, then run `pnpm dev` inside this directory. Open
<http://127.0.0.1:5173>. Vite proxies `/api` to port 8787 and rewrites the Origin
header **only** for the two explicitly allowed loopback development origins.
The production API accepts same-origin JSON mutations on loopback hostnames.

The server is intended for a trusted workstation. It has no multi-user
authentication and the CLI binds to `127.0.0.1`. Model and tool secrets never
need to enter the browser. Fonts use local system fallbacks; the inspector does
not fetch a remote font, analytics script, or CDN asset.

## What the controls do

- **New experiment**: run a scripted scenario against a separate simulated
  provider database. The simulated-provider label remains visible.
- **Resume run**: use the recorded demo policy to reconcile outstanding work.
  Live model sessions must be resumed through their originating adapter.
- **Execution trace**: select any persisted event and inspect its full payload.
  Recovery filtering narrows the trace without modifying it.
- **Operations → Confirm result**: explicitly record an independently verified
  outcome and evidence note for an uncertain demo operation. Opening the dialog
  does not approve or resolve anything.
- **Export trace**: download the current snapshot as JSON. This reads the journal
  and never repeats a tool call.

While a selected run is active, its snapshot is polled every three seconds.
`GET /api/runs/{id}/events` also provides a finite SSE snapshot; reconnect using
`Last-Event-ID` or `?after=<sequence>` to read newly committed events.

## End-to-end smoke

Use a disposable data directory. In a separate terminal:

```sh
rebound serve --data /tmp/rebound-inspector-smoke --port 8787
```

Then, from `frontend/`:

```sh
pnpm exec playwright install chromium
pnpm smoke
```

The script creates experiments, verifies recovery and review states, exports
the real trace, checks browser errors and desktop/mobile overflow, and saves
actual screenshots in `docs/assets/`. Set `SCREENSHOT_DIR` to change that output,
or `BASE_URL=http://127.0.0.1:5173` to verify the development proxy. To use an
existing browser binary, set `BROWSER_EXECUTABLE` to its executable path. Every
run creates an isolated browser context; no existing profile is used.

Set `QA_SCREENSHOT_DIR` to an output directory to additionally render the
authored documentation SVGs and reference benchmark chart into review PNGs.
This is optional and does not alter the original diagrams. CI uploads these
previews separately from the actual inspector screenshots.

`pnpm build` checks TypeScript before bundling. `pnpm format` formats source with
Prettier. Dialogs use native focus trapping, tabs support arrow keys, reduced
motion is respected, and every action has loading and failure states.
