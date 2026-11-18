"""Modal deployment for the NEAR Video Clipping Agent.

Run from the repo root:
    modal deploy modal_app.py

The deployed web endpoint serves the same API as clipper/server.py
(GET /health, POST /clip, POST /clip-sync, GET /jobs/{id}, ...).

Auth: CLIPPER_TOKEN comes from a Modal Secret named "clipper-token".
Create it once (after `modal setup`) with:
    modal secret create clipper-token \
        CLIPPER_TOKEN=$(cat hidden_files/cloudrun-token.txt)
The token value is NEVER committed to the repo.

Cost: CPU-only web endpoint, billed per second while a request runs.
One ~170 s job on 2 CPU / 4 GiB is roughly $0.006, so the $30/month
Starter credits cover ~5,000 such jobs. Idle time costs nothing
(the endpoint scales to zero).
"""
from pathlib import Path
import subprocess

import modal

ROOT = Path(__file__).parent

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install_from_requirements(str(ROOT / "requirements.txt"))
    # Pre-download the whisper tiny model at image-build time so the
    # first request does not pay the download.
    # NOTE: Modal forbids any build step (run_commands, pip_install,
    # apt_install) AFTER an add_local_* call, so ALL build steps must
    # come before .add_local_dir() below. The first deploy failed on
    # exactly this: run_commands() sat after add_local_dir().
    .run_commands(
        "python -c \"from faster_whisper import WhisperModel; "
        "WhisperModel('tiny', device='cpu', compute_type='int8')\""
    )
    .add_local_dir(str(ROOT / "src"), remote_path="/root/clipper")
)

app = modal.App("near-clipper")


@app.function(
    image=image,
    cpu=2,
    memory=4096,
    timeout=3600,
    secrets=[modal.Secret.from_name("clipper-token")],
    env={
        "PORT": "8080",
        "PYTHONPATH": "/root/clipper",
        "CLIPPER_OUT": "/tmp/clipper-out",
    },
)
@modal.web_server(port=8080, startup_timeout=180)
def serve():
    subprocess.Popen(["python", "-m", "clipper.server", "8080"])
