# syntax=docker/dockerfile:1
# Spotlight motion worker: Wan 2.2 TI2V-5B image-to-video on Azure Container Apps serverless GPU (A100).
#
# Base = Microsoft's ACA GPU quickstart image, pinned by digest (Azure Linux, python 3.12 in the system
# site-packages, torch 2.8.0+cu126, diffusers 0.40.0, transformers, accelerate, huggingface_hub, numpy, pillow).
# That image runs as root and ships its own ENTRYPOINT/CMD (a Stable Diffusion demo): both are replaced below.
# Build (cloud build, no Docker daemon needed):  see README.md "Build".
FROM mcr.microsoft.com/k8se/gpu-quickstart@sha256:ad47b0adb21075d21fd3c6a8786cbc21a09a276f278102163d8809ab0f9712b3

USER root

# At runtime the container is non-root and only /tmp is writable: every cache/work dir lives under /tmp.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    HF_HOME=/tmp/hf \
    HOME=/tmp/home \
    XDG_CACHE_HOME=/tmp/.cache \
    TORCH_HOME=/tmp/torch \
    TRITON_CACHE_DIR=/tmp/triton \
    MPLCONFIGDIR=/tmp/mpl \
    TMPDIR=/tmp

# Missing from the base image: azure SDKs (queue/blob/identity), ftfy (required by the Wan text pipeline), imageio +
# imageio-ffmpeg (bundled static ffmpeg with libx264 for the encode step). Everything is pinned in requirements.txt;
# numpy/pillow/torch/diffusers come from the base and are not touched.
COPY requirements.txt /opt/motion/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/motion/requirements.txt \
    && python -c "import azure.identity, azure.storage.blob, azure.storage.queue, ftfy, imageio, imageio_ffmpeg, numpy, PIL; print('dependencies ok')" \
    && python -c "import subprocess, imageio_ffmpeg; exe = imageio_ffmpeg.get_ffmpeg_exe(); out = subprocess.run([exe, '-hide_banner', '-encoders'], capture_output=True, text=True, check=True).stdout; assert 'libx264' in out, 'bundled ffmpeg has no libx264'; print('ffmpeg ok', exe)" \
    && python -c "import torch, diffusers; from diffusers import AutoencoderKLWan, WanImageToVideoPipeline; print('torch', torch.__version__, 'diffusers', diffusers.__version__)"

WORKDIR /app
COPY motion_worker/ /app/motion_worker/
RUN chmod -R a+rX /app/motion_worker \
    && python -m compileall -q /app/motion_worker

# Unprivileged runtime user (same uid as the Studio image). useradd exists on Azure Linux; the fallback edits
# passwd/group directly. Dirs under /tmp are sticky + world-writable so any uid the platform picks can use them.
RUN if command -v useradd >/dev/null 2>&1; then \
        groupadd --gid 10001 motion \
        && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp/home --shell /sbin/nologin motion; \
    else \
        echo "motion:x:10001:" >> /etc/group \
        && echo "motion:x:10001:10001:motion:/tmp/home:/sbin/nologin" >> /etc/passwd; \
    fi \
    && mkdir -p /tmp/models /tmp/motion-work /tmp/hf /tmp/home /tmp/.cache /tmp/torch /tmp/triton /tmp/mpl \
    && chmod 1777 /tmp/models /tmp/motion-work /tmp/hf /tmp/home /tmp/.cache /tmp/torch /tmp/triton /tmp/mpl

LABEL org.opencontainers.image.title="spotlight-motion-worker" \
      org.opencontainers.image.description="Wan 2.2 TI2V-5B (Apache-2.0) image-to-video worker for Spotlight, queue + blob contract v1"

USER 10001:10001
ENTRYPOINT ["python", "-m", "motion_worker"]
CMD []
