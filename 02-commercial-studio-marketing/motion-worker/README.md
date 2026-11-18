# Spotlight motion worker (GPU)

Self-hosted **image-to-video** for the Commercial Studio ("Spotlight") *cinematic* render: the approved storyboard keyframe
becomes the first frame of an AI-generated clip with real subject and camera motion, and the existing compositor then edits the
clips into the spot. The model is **Wan 2.2 TI2V-5B** (Apache-2.0, `Wan-AI/Wan2.2-TI2V-5B-Diffusers`, pinned to revision
`b8fff7315c768468a5333511427288870b2e9635`) running on **Azure Container Apps serverless GPU (NC24-A100)** — scale-to-zero,
**no ingress**, keyless (managed identity), data never leaves the tenant.

The worker talks to the Studio only through **one Storage queue + blob containers**, defined in
[`../contracts/`](../contracts/README.md) (schema, golden job-id vectors, producer/consumer protocol). It processes **one job at
a time** (quota: exactly one A100 replica per environment).

```
Studio ──blob motion-in/<job>/{image,request.json}──► queue motion-jobs ──(KEDA azure-queue, identity)──► ca-studio-motion (GPU)
Studio ◄──blob motion-out/<job>/{status,result}.json, clip.mp4, _worker/ready.json──────────────────────────────┘
```

## What is in here

| Path | Purpose |
|---|---|
| `motion_worker/contract.py` | wire contract in code: `compute_job_id`, request validation, document builders |
| `motion_worker/transport.py` | `AzureTransport` (Queue + Blob, Entra only) and `LocalTransport` (directory, Azure-like semantics) |
| `motion_worker/weights.py` | local dir → blob mirror (`motion-models`, size-verified via `manifest.json`) → Hugging Face, then write-through |
| `motion_worker/pipeline.py` | `WanPipeline` (diffusers, GPU) and `FakePipeline` (CPU, deterministic *moving* clip) |
| `motion_worker/worker.py` | main loop, heartbeat/visibility renewal, status + ready writers, poison guard, OOM mapping, SIGTERM, watchdog |
| `motion_worker/submit.py` | producer tool: enqueue a job / warm-up the same way the Studio does (local or Azure) |
| `Dockerfile`, `requirements.txt` | image: pinned base digest, pinned extra wheels, non-root, `/tmp` only |
| `tests/` | CPU-only suite (no network, no GPU, no Azure): 346 tests, 98 % line+branch coverage |

## Run it locally (no GPU, no Azure)

```bash
cd 02-commercial-studio-marketing/motion-worker
python -m pip install -r requirements.txt -r requirements-dev.txt        # or use the repo venv

export MOTION_PIPELINE=fake MOTION_TRANSPORT=local MOTION_LOCAL_DIR=./.motion MOTION_WORK_DIR=./.motion-work
python -m motion_worker &                                                 # JSON logs on stdout, Ctrl-C / SIGTERM = graceful stop

python -m motion_worker.submit --image keyframe.jpg --prompt "slow push-in, steam rises" \
       --width 1024 --height 576 --frames 73 --steps 20 --wait 120 --out clip.mp4
```

`MOTION_PIPELINE=fake` produces a real, H.264, 24 fps clip with a seeded push-in/drift/roll and a light sweep (frame 0 is the
input image); it needs ffmpeg (system binary or the `imageio-ffmpeg` wheel). Dev knobs: `MOTION_FAKE_STEP_DELAY_S` (watch
`status.json` progress), `MOTION_FAKE_LOAD_DELAY_S`, `MOTION_EXIT_WHEN_IDLE_S` (drain the queue, then exit), and prompt markers
`[fake:oom]` / `[fake:error]` to inject a CUDA OOM / an internal error. The fake reports `model_revision: "fake"`.

`python -m motion_worker --print-config` prints the resolved configuration; exit codes: `0` ok, `1` fatal runtime error, `2`
invalid configuration, `3` initialisation failure, `70` hang watchdog (replica restart).

## Configuration (environment)

| Variable | Default | Meaning |
|---|---|---|
| `MOTION_TRANSPORT` | `azure` | `azure` \| `local` |
| `MOTION_PIPELINE` | `wan` | `wan` (GPU) \| `fake` (CPU) |
| `AZURE_CLIENT_ID` | – | client id of the **user-assigned managed identity** (`DefaultAzureCredential(managed_identity_client_id=…)`) |
| `MOTION_STORAGE_ACCOUNT_URL` | – (azure: required) | blob account URL, `https://<acct>.blob.core.windows.net` |
| `MOTION_QUEUE_URL` | – (azure: required) | queue account URL, `https://<acct>.queue.core.windows.net` |
| `MOTION_QUEUE_NAME` | `motion-jobs` | queue |
| `MOTION_IN_CONTAINER` / `MOTION_OUT_CONTAINER` / `MOTION_MODELS_CONTAINER` | `motion-in` / `motion-out` / `motion-models` | blob containers |
| `MOTION_LOCAL_DIR` | – (local: required) | root of the local-dir transport |
| `MOTION_MODEL_ID` | `wan2.2-ti2v-5b` | model served; requests for another model get `bad_request` |
| `MOTION_MODEL_REPO` / `MOTION_MODEL_REVISION` | `Wan-AI/Wan2.2-TI2V-5B-Diffusers` / `b8fff73…9635` | upstream weights (required for unknown model ids) |
| `MOTION_MODEL_DIR` | `/tmp/models` | local weights cache |
| `MOTION_WORK_DIR` | `/tmp/motion-work` | scratch (wiped at start/exit — must be a dedicated directory) |
| `MOTION_VISIBILITY_TIMEOUT_S` | `600` | queue visibility timeout |
| `MOTION_RENEW_INTERVAL_S` | `60` | visibility renewal (≤ 120 and ≤ half of the timeout) |
| `MOTION_STATUS_INTERVAL_S` | `2` | `status.json` cadence (≤ 3) |
| `MOTION_READY_INTERVAL_S` | `60` | `ready.json` refresh (≤ 90) |
| `MOTION_POLL_INTERVAL_S` | `2` | idle queue polling |
| `MOTION_MAX_DEQUEUE` | `3` | poison guard: deliveries above this are failed, not run |
| `MOTION_JOB_TIMEOUT_S` | `600` | per-job limit (checked at every denoising step → `timeout`) |
| `MOTION_WATCHDOG_GRACE_S` | `120` | a job stuck beyond limit + grace is failed and the process exits (code 70) |
| `MOTION_SHUTDOWN_GRACE_S` / `MOTION_SHUTDOWN_MARGIN_S` | `600` / `30` | SIGTERM: finish the job if it can within grace − margin, else abort + release the message. **Set the same value as the container's `terminationGracePeriodSeconds`** |
| `MOTION_MIRROR` | `1` | write freshly downloaded weights through to `motion-models` (background, resumable) |
| `MOTION_MIRROR_BF16` | `0` | opt-in: mirror a bf16 transformer (~23 GiB instead of ~32 GiB); falls back to upstream if a mirror copy fails to load |
| `MOTION_DOWNLOAD_WORKERS` / `MOTION_BLOB_CONCURRENCY` | `4` / `8` | parallel files / parallel ranges per blob |
| `MOTION_WARMUP_GENERATE` | `0` | opt-in tiny generation on the first warm-up message (primes CUDA kernels) |
| `MOTION_FFMPEG` | – | explicit ffmpeg binary (default: bundled `imageio-ffmpeg`, else `ffmpeg` on PATH) |
| `MOTION_REPLICA` | `CONTAINER_APP_REPLICA_NAME` → hostname | name written into `status.json`/`ready.json` |
| `MOTION_EXIT_WHEN_IDLE_S` | `0` | dev: exit after the queue was empty for N s |
| `MOTION_LOG_LEVEL` | `INFO` | |

No keys, SAS tokens or connection strings exist anywhere (a test greps for them).

## The generation call (proven on the A100 spike)

`AutoencoderKLWan.from_pretrained(path, subfolder="vae", torch_dtype=torch.float32)` →
`WanImageToVideoPipeline.from_pretrained(path, vae=vae, torch_dtype=torch.bfloat16).to("cuda")` → per job
`pipe(image, prompt, negative_prompt, height, width, num_frames, guidance_scale, num_inference_steps, generator=torch.Generator("cuda").manual_seed(seed), output_type="np", callback_on_step_end=…)`.
Note: diffusers 0.40's default `output_type` is `"np"` (float array `(T,H,W,3)` in [0,1]), not PIL — the worker passes it
explicitly and converts per frame. The callback follows diffusers' `(pipe, step, timestep, kwargs) -> kwargs` convention and is
where progress, the job timeout and the shutdown-abort are enforced. The frames are piped to ffmpeg:
`libx264 -preset medium -crf 17 -pix_fmt yuv420p`, BT.709 tagged, `+faststart`, silent, 24 fps. The input image is
centre-cropped to the target aspect and LANCZOS-resized before conditioning; frames are 4n+1, sizes multiples of 32.

## Cold start (scale-from-zero) — what to expect

| Phase | Measured on the spike (swedencentral A100) | In this worker |
|---|---|---|
| Image pull | (platform) — the base image is ~7 GiB; our layers add < 200 MB | – |
| Weights | HF download ≈ 226 s for 32 GiB | local → **blob mirror** → HF; the first start downloads from HF and mirrors in the background (resumable, manifest last) |
| Load to GPU | 12 s, 22.6 GiB resident | `ready.json` goes `loading` → `ready` |
| Generation | 1024×576, 73 frames, 20 steps ≈ 55 s; 109 frames ≈ 88 s; 1280×704 ≈ 92 s | `gpu_seconds` ≈ generate + encode + a second or two of I/O |

Studio's `est_cold_start_s=240` is the HF path; the mirror path depends on blob throughput (measure on the first live run). The
Studio's warm-up message (sent after the storyboard) hides most of it.

## Build

No Docker daemon is needed (cloud build). From this directory:

```bash
az acr build --subscription 1217c203-6c76-47b4-b61c-9bba62dc8e02 \
  --registry <acr-name> --image spotlight-motion-worker:<tag> --file Dockerfile .
```

The first build pulls the 7 GiB base (`mcr.microsoft.com/k8se/gpu-quickstart@sha256:ad47b0ad…712b3`, Azure Linux, python 3.12,
torch 2.8.0+cu126, diffusers 0.40.0) — expect minutes. The build installs only the pinned wheels from `requirements.txt`
(azure-identity, azure-storage-blob, azure-storage-queue, ftfy, imageio, imageio-ffmpeg) and fails fast if the Azure SDKs, the
bundled ffmpeg (libx264) or `AutoencoderKLWan`/`WanImageToVideoPipeline` cannot be imported. The image runs as uid `10001`; all
caches and scratch live under `/tmp` (`HF_HOME`, `HOME`, `TORCH_HOME`, …); `ENTRYPOINT ["python","-m","motion_worker"]` replaces
the base image's demo entrypoint.

## Deploying (for the infra owner)

* Container App `ca-studio-motion`: workload profile **`gpu-a100`**, **no ingress**, `cpu: 8`, `memory: 64Gi`, scale
  **min 0 / max 1**, user-assigned identity (`AZURE_CLIENT_ID`), env from the table above, **`terminationGracePeriodSeconds: 600`**
  (and `MOTION_SHUTDOWN_GRACE_S=600`).
* **Scale rule** (KEDA `azure-queue`): `queueName: motion-jobs`, `queueLength: 1`, `accountName: <storage account>`,
  identity-based auth with the same managed identity; keep `queueLengthStrategy` at its default `all` (the scaler then counts
  in-flight messages too — checked against KEDA's `azure_queue_scaler.go` — so the replica is not scaled in while a job runs, and an
  undeleted message would block scale-to-zero; the worker deletes every finished message). Cooldown ≥ 300 s.
* **One GPU ⇒ one replica ever:** a revision update needs the old replica gone first (single-revision mode keeps the old
  revision until the new one is healthy, and there is no second GPU) — scale to 0 / deactivate the old revision before rolling.
* **RBAC** (per the contract, §10): worker identity = *Storage Queue Data Message Processor* + *Storage Blob Data Contributor*;
  the scaler (and the Studio, for `queue_depth`) additionally needs queue **read** (*Storage Queue Data Reader*) because Get
  Queue Properties is a `queues/read` operation. If visibility renewals ever log `AuthorizationPermissionMismatch`, grant
  *Storage Queue Data Contributor* instead (verify on the first live run — renewal failures are non-fatal).
* Storage: containers `motion-in`, `motion-out`, `motion-models`, queue `motion-jobs`; shared-key access stays off. Suggested
  lifecycle rule: delete `motion-out` blobs after 7 days.
* No Cosmos / Azure OpenAI access is needed or granted.

## Operating notes

* Logs are JSON lines (`event`, `job_id`, `shot_id`, `gpu_seconds`, `state`, …). Useful events: `worker_ready`, `weights_ready`
  (source `local|mirror|hf`), `job_start`, `job_done`, `job_failed` (`error_code`), `job_skipped`, `job_poison`, `job_aborted`,
  `job_stuck`, `job_id_mismatch`, `message_lost`, `receive_failed`, `mirror_upload_*`. Prompts are never logged.
* Failure mapping: CUDA/host OOM → `oom` (not retryable); bad input → `bad_request`; step-time limit → `timeout`; anything
  else → `internal`. The message is deleted after a terminal result; an unexpected crash leaves it to reappear (≤ 3 deliveries).
* A GPU call that hangs cannot be interrupted from Python: the watchdog fails the job and exits with code 70 so the platform
  restarts the replica (a cold start, but no lost money on a zombie).
* Weights: `motion-models/<model_id>/<revision>/…` + `manifest.json` (written last; sizes verified on download). A corrupt mirror
  copy that fails to load is detected, the worker rebuilds from Hugging Face once and re-uploads the mirror.

## Tests

```bash
python -m pytest                      # unit + behavioural, ≥ 85 % coverage enforced (currently ~98 %)
python -m ruff check . && python -m ruff format --check .
```

Everything runs on CPU without network: local transport round-trips, idempotency, poison guard, failure mapping, deterministic
job id (golden vectors shared with the Studio), schema validation of every JSON the worker writes, monotonic progress,
warm-up, SIGTERM (real signals and a real subprocess), the hang watchdog, queue outages, weights logic with a fake mirror/HF, the
fake pipeline's clip genuinely moving (checked on the *decoded* H.264), and static guards for the Dockerfile. The Azure
transport is exercised with SDK-faithful fakes **and, when the SDKs are installed, through the real `azure-storage-queue`/`-blob`
clients over a canned HTTP layer** (this caught an enum-vs-string error-code bug). `WanPipeline` runs against a fake torch/diffusers
whose `__call__` signature is copied from diffusers 0.40.0.

**What is not verified here:** the real model on a real GPU, the real Azure services, and the Docker build (no daemon) — the first
live run is the integration test; the Dockerfile's build-time import checks are designed to fail early and clearly.

## Licences

Wan 2.2 TI2V-5B: Apache-2.0 (model weights from Hugging Face, pinned revision). Python deps: azure-* (MIT), ftfy (Apache-2.0),
imageio / imageio-ffmpeg (BSD-2). `imageio-ffmpeg` ships a static ffmpeg build (GPL, includes libx264) that is **executed as a
separate process only** (never linked).
