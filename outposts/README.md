# Modal-backed Devin outpost

`gpu_h100.py` deploys a [Devin outpost](https://docs.devin.ai) worker onto Modal, so Devin
sessions run inside a Modal Sandbox with a real H100 instead of the default CPU-only Devin VM.
Sessions start on a prebaked checkout of this repo with `torch`, `triton`, and the `[dev]` extras
already installed, so `pytest test/` and the benchmarks run immediately.

## Deploy

```bash
uv venv && uv pip install modal-devin
export MODAL_TOKEN_ID=... MODAL_TOKEN_SECRET=...   # https://modal.com/settings/tokens
uv run modal deploy --strategy rolling outposts/gpu_h100.py
```

The app expects a Modal secret named `devin-outposts-token` holding `DEVIN_OUTPOSTS_TOKEN`, an
admin-scoped Devin Enterprise service-user key:

```bash
uv run modal secret create devin-outposts-token DEVIN_OUTPOSTS_TOKEN=...
```

The outpost itself (`gpu-h100`, `outpost_env-4d276f55e8024d338ddba4fc68c36178`) was created with
`uvx modal-devin init gpu-h100 --api-url https://api.devin.ai`. Note the non-default `--api-url`:
modal-devin defaults to `api.beta.devinenterprise.com`, which returns 403 for this org.

## Using it

Pick `gpu-h100` under Configuration → Virtual environment in the Devin webapp, or from Slack:

```text
@Devin !outpost gpu-h100 profile the fused linear cross entropy kernel and fix the slowest part
```

## Cost

Modal bills only while a session runs. A 4-core/16 GiB sandbox is ~$0.95/hr plus the GPU
(H100 ~$3.95/hr), so ~$4.90/hr of session time; the scheduler polls on a CPU container and is
single-digit dollars a month. Downgrade `gpu="H100"` to `"A10G"` or `"L40S"` for cheaper runs.

## Known issue: the CLI shim

modal-devin 0.1.12 runs `devin worker start --pool <id>` and asserts `--pool` shows up in
`--help` at image build time. Devin CLI 3000.6.x renamed that flag to `--outpost`, so the stock
`worker.base_image()` fails to build. `gpu_h100.py` installs a small wrapper around the CLI that
translates the flag; delete `DEVIN_CLI_SHIM` and go back to `worker.base_image()` once modal-devin
targets the current CLI.
