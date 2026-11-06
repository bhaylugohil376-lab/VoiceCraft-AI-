# VoiceCraft AI — CPU voice conversion worker

This is a separate, self-hosted API adapter for **Applio/RVC inference**. It does not train or clone a voice. It converts an uploaded recording using an already-trained inference model that you are authorized to use.

## Important deployment requirements

- A Linux VPS or dedicated server with enough RAM, disk, and CPU time. GitHub Pages and Supabase Edge Functions cannot host this long-running ML process.
- Python 3.12 and a working Applio installation at `APPLIO_ROOT`.
- At least one compatible Applio inference export (`.pth`). Add its matching `.index` when supplied by the model publisher. A training checkpoint such as `G_*.pth` is not an inference model.
- CPU inference can be slow. A short sample should be tested first. No GPU is required by this worker; CUDA devices are hidden for its inference subprocess.

Applio's documented CLI command is `python core.py infer --input-path ... --output-path ... --pth-path ... --index-path ...`. Check the installed Applio release's `python core.py infer --help` before production use because flags can vary by version.

## Install Applio separately

Follow the official installation guide for the chosen Linux release:
https://docs.applio.org/getting-started/installation/

For a source installation, the documented starting commands are:

```bash
git clone --recurse-submodules https://github.com/IAHispano/Applio.git /opt/Applio
cd /opt/Applio
bash run-install.sh
```

Complete the installation and verify `python core.py infer --help` in Applio's own Python environment. If Applio uses a virtual environment, set `PYTHON_BIN` to that environment's Python and use it to launch this API too.

## Configure permitted inference models

Copy `models.example.json` to `models.json`. Place model files under `VOICE_MODELS_DIR` (default: `/opt/Applio/logs`) and update each entry's relative paths. Only list voices and recordings you have permission to use. Never commit model weights or private recordings to Git.

## Run the API

```bash
cd voice-changer-worker
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export APPLIO_ROOT=/opt/Applio
export VOICE_MODELS_DIR=/opt/Applio/logs
export VOICE_MODELS_JSON=$PWD/models.json
export VOICE_WORKER_TOKEN='use-a-long-random-secret'
export VOICE_WORKER_CORS_ORIGINS='https://bhaylugohil376-lab.github.io'
uvicorn app:app --host 0.0.0.0 --port 8787
```

Set a strong secret outside source control and terminate TLS with a reverse proxy. Do not expose this API publicly over plain HTTP. Restrict the firewall to HTTPS and consider adding request-rate limits at the proxy.

## API

- `GET /health` — readiness summary; no secrets are returned.
- `GET /voices` — configured and present models. Requires `Authorization: Bearer <VOICE_WORKER_TOKEN>`.
- `POST /convert?model_id=<id>` — multipart field `audio`, maximum 20 MB. Requires the same bearer token. Returns a WAV file.

Conversion is serialized to avoid concurrent CPU/RAM overload. Default timeout is 900 seconds; configure `CONVERSION_TIMEOUT_SECONDS` and `MAX_UPLOAD_BYTES` as needed.

## Not yet production-connected

This worker is a deployable integration scaffold, not a claim that the VoiceCraft website is already connected. Before enabling the Convert button, deploy it on a server, install Applio in that server's Python environment, add and verify compatible voice models, configure HTTPS/CORS/token handling, and run an end-to-end conversion. Do not place the bearer token in browser JavaScript; route requests through a protected server-side proxy or short-lived authenticated session.
