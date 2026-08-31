"""Modal application for one Devin worker.

Generated once by modal-devin. This is application code and may be edited.
"""

import base64
import os

import modal

from modal_devin import Worker

worker = Worker.from_env(
    "gpu-h100",
    outpost_id="outpost_env-4d276f55e8024d338ddba4fc68c36178",
    api_url="https://api.devin.ai",
)

app = modal.App(
    "modal-devin-gpu-h100",
    tags={"service": "modal-devin"},
)
devin_secret = modal.Secret.from_name("devin-outposts-token")
controller_image = worker.controller_image()

REPO_URL = "https://github.com/ananthv26-cog-demo-repos/Liger-Kernel"
REPO_DIR = "/root/workspace/Liger-Kernel"
# Modal caches image layers by definition, so the clone layer only rebuilds when this changes.
# Deploy with OUTPOST_REPO_REF=<sha or branch> to refresh the prebaked checkout.
REPO_REF = os.environ.get("OUTPOST_REPO_REF", "main")

# Versions the outpost is verified against; bump deliberately rather than floating.
TORCH_VERSION = "2.13.0"
TRITON_VERSION = "3.7.1"

DEVIN_BIN = "/root/.local/bin/devin"
DEVIN_REAL_BIN = "/root/.local/share/devin/cli/_versions/current/bin/devin"

# modal-devin 0.1.12 invokes `devin worker start --pool <id>` and asserts `--pool` appears in
# `--help`. Devin CLI 3000.6.x renamed that flag to `--outpost`, so the stock
# `worker.base_image()` fails its build-time contract check. This shim translates the flag and
# re-advertises it in --help; drop it once modal-devin targets the current CLI.
DEVIN_CLI_SHIM = r"""#!/usr/bin/env python3
import os
import subprocess
import sys

REAL = "/root/.local/share/devin/cli/_versions/current/bin/devin"
args = ["--outpost" if a == "--pool" else a for a in sys.argv[1:]]

if "--help" in args or "-h" in args:
    done = subprocess.run([REAL, *args], capture_output=True, text=True)
    sys.stdout.write(done.stdout)
    if args[:2] == ["worker", "start"]:
        sys.stdout.write("      --pool <OUTPOST>\n          Alias for --outpost\n")
    sys.stderr.write(done.stderr)
    raise SystemExit(done.returncode)

os.execv(REAL, [REAL, *args])
"""

# Equivalent to worker.base_image(), rebuilt here so the shim lands before the contract check.
base_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl", "ca-certificates", "tar", "build-essential", "ripgrep")
    .run_commands(
        f"curl -fsSL https://cli.devin.ai/install.sh | bash; test -x {DEVIN_REAL_BIN}",
        f"rm -f {DEVIN_BIN}",
        f"echo {base64.b64encode(DEVIN_CLI_SHIM.encode()).decode()} | base64 -d > {DEVIN_BIN}",
        f"chmod 0755 {DEVIN_BIN}",
        f"{DEVIN_BIN} worker start --help > /tmp/devin-worker-help"
        " && grep -q -- '--session' /tmp/devin-worker-help"
        " && grep -q -- '--pool' /tmp/devin-worker-help"
        " && grep -q -- '--acceptor-id' /tmp/devin-worker-help"
        " && grep -q 'DEVIN_REMOTE_SESSION_TOKEN' /tmp/devin-worker-help"
        " && rm /tmp/devin-worker-help",
    )
    .apt_install("ffmpeg", "chromium")
    .env({"DEVIN_CHROME_PATH": "/usr/bin/chromium"})
    # Prebake the workload so a session starts on a warm checkout instead of a 10-minute
    # torch/triton install.
    .run_commands(
        f"git clone {REPO_URL} {REPO_DIR} && git -C {REPO_DIR} checkout {REPO_REF}",
        f"pip install --no-cache-dir torch=={TORCH_VERSION} triton=={TRITON_VERSION}",
        f'cd {REPO_DIR} && pip install --no-cache-dir -e ".[dev]"',
    )
)

# Adds the modal-devin runtime after all user image customization.
image = worker.prepare_image(base_image)


@app.function(
    name="session",
    image=image,
    secrets=[devin_secret],
    timeout=worker.session_function_timeout_seconds,
)
def session(session_id: str) -> None:
    worker.run_session(
        session_id,
        app=app,
        image=image,
        # Sandbox options are typed from modal.Sandbox.create:
        gpu="H100",
        cpu=4,
        memory=16384,
    )


@app.function(
    name="scheduler",
    image=controller_image,
    secrets=[devin_secret],
    schedule=modal.Period(seconds=worker.settings.scheduler_interval_seconds),
    max_containers=1,
)
def scheduler() -> None:
    worker.dispatch_pending_sessions(session.spawn)
