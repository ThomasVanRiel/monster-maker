# GPU worker for the gaming PC (RTX 4070 Ti Super): FLUX.2 [klein] and TRELLIS.2 plus the pull loop.
# Built in CI (.github/workflows/gpu.yml), never on the PC. Model weights are not in the image:
# they download once into the /cache volume (Hugging Face; DINOv3 needs HF_TOKEN, see .env.example).
# diffusers stays at 0.38: later releases need huggingface-hub 1.x, which transformers 4 (TRELLIS's
# pin) refuses.
#
# Versions follow TRELLIS.2's setup.sh: Python 3.10, CUDA 12.4, torch 2.6.0, flash-attn 2.7.3.
# The CUDA extensions compile for TORCH_CUDA_ARCH_LIST only (8.9 = Ada, the 4070 Ti Super):
# CI has no GPU to detect.

ARG CUDA=12.4.1
ARG TRELLIS_REF=75fbf0183001ed9876c8dbb35de6b68552ee08bd
ARG NVDIFFRAST_REF=v0.4.0
ARG CUMESH_REF=12289e1062f0603f2f0d0771b02e1395d247f26f
ARG FLEXGEMM_REF=6dd94a859c26ee8246888502eada3dd8ad85532e
ARG UTILS3D_REF=9a4eb15e4021b67b12c460c7057d642626897ec8

# --- build: compile the CUDA extensions --------------------------------------------------------
FROM nvidia/cuda:${CUDA}-devel-ubuntu22.04 AS build
ARG TRELLIS_REF NVDIFFRAST_REF CUMESH_REF FLEXGEMM_REF UTILS3D_REF
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PATH=/venv/bin:$PATH \
    TORCH_CUDA_ARCH_LIST=8.9 MAX_JOBS=4 BUILD_TARGET=cuda
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3.10-dev git build-essential ninja-build ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN python3.10 -m venv /venv && pip install --upgrade pip setuptools wheel
RUN pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
# setup.sh --basic, without the demo/training extras (gradio, tensorboard, lpips, pandas)
RUN pip install imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja trimesh \
        "transformers>=4.56,<5" zstandard kornia timm pillow plyfile filelock httpx \
        "git+https://github.com/EasternJournalist/utils3d.git@${UTILS3D_REF}" \
    && pip install "https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.3/flash_attn-2.7.3+cu12torch2.6cxx11abiFALSE-cp310-cp310-linux_x86_64.whl"

WORKDIR /src
RUN git clone https://github.com/NVlabs/nvdiffrast.git && git -C nvdiffrast checkout ${NVDIFFRAST_REF} \
    && pip install ./nvdiffrast --no-build-isolation
RUN git clone --recursive https://github.com/JeffreyXiang/CuMesh.git \
    && git -C CuMesh checkout ${CUMESH_REF} && git -C CuMesh submodule update --init --recursive \
    && pip install ./CuMesh --no-build-isolation
RUN git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git \
    && git -C FlexGEMM checkout ${FLEXGEMM_REF} && git -C FlexGEMM submodule update --init --recursive \
    && pip install ./FlexGEMM --no-build-isolation \
    && cp ~/.flex_gemm/autotune_cache.json /venv/flex_gemm_autotune_cache.json
# o-voxel compiles against Eigen, TRELLIS.2's one git submodule (o-voxel/third_party/eigen)
RUN git clone https://github.com/microsoft/TRELLIS.2.git /opt/trellis2 && git -C /opt/trellis2 checkout ${TRELLIS_REF} \
    && git -C /opt/trellis2 submodule update --init --recursive \
    && pip install /opt/trellis2/o-voxel --no-build-isolation --no-deps \
    && rm -rf /opt/trellis2/.git /opt/trellis2/assets
# FLUX.2 [klein] (imagine step) and BiRefNet's remote code; last, so the CUDA builds above stay cached
RUN pip install diffusers==0.38.0 "accelerate>=1.0,<2" einops

# --- runtime -----------------------------------------------------------------------------------
FROM nvidia/cuda:${CUDA}-runtime-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive
# gcc and the Python headers: Triton (FlexGEMM's kernels) builds a small launcher on first use
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-dev gcc libgl1 libglib2.0-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /venv /venv
COPY --from=build /opt/trellis2 /opt/trellis2

# Everything that downloads or caches goes to the /cache volume, so the container can run as the
# PC's user and the ~35 GB of weights survive image updates.
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONPATH=/opt/trellis2:/app \
    HOME=/cache HF_HOME=/cache/huggingface HF_HUB_DISABLE_TELEMETRY=1 \
    TRITON_CACHE_DIR=/cache/triton FLEX_GEMM_AUTOTUNE_CACHE_PATH=/cache/flex_gemm/autotune_cache.json \
    ATTN_BACKEND=flash_attn OPENCV_IO_ENABLE_OPENEXR=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

WORKDIR /app
COPY monster_gpu ./monster_gpu
COPY entrypoint.sh /entrypoint.sh
VOLUME /cache
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "monster_gpu.worker"]
