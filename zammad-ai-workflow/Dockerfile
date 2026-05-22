# Smallest ubi10 image
FROM registry.access.redhat.com/ubi10/ubi-minimal:latest@sha256:01a3f76f9f6734c637e328111b0f48100e8d8ad41ead12fc3ff0b57a952dd7ea

COPY --from=ghcr.io/astral-sh/uv:latest@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 /uv /uvx /bin/

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Leverage layer cache
COPY pyproject.toml uv.lock ./

# Install the transitive dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --locked --no-install-project

# Pre-download the guardrail model into the image cache so startup does not
# need to fetch it on first boot.
ARG GUARDRAIL_MODEL_NAME="fastino/gliguard-LLMGuardrails-300M"
RUN /app/.venv/bin/python -c "from gliner2 import GLiNER2; model = GLiNER2.from_pretrained(\"$GUARDRAIL_MODEL_NAME\", local_files_only=True); model.to(\"cpu\")"

# Copy the application files
COPY . /app

# Install the project
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --locked

# Metadata for the image
ARG IMAGE_CREATED="unknown"
ARG IMAGE_REVISION="unknown"
ARG IMAGE_VERSION="unknown"
LABEL org.opencontainers.image.authors='Landeshauptstadt München <opensource@muenchen.de>' \
    org.opencontainers.image.vendor='Landeshauptstadt München' \
    org.opencontainers.image.created="$IMAGE_CREATED" \
    org.opencontainers.image.revision="$IMAGE_REVISION" \
    org.opencontainers.image.version="$IMAGE_VERSION" \
    org.opencontainers.image.url='https://github.com/it-at-m/zammad-ai' \
    org.opencontainers.image.documentation='https://github.com/it-at-m/zammad-ai/blob/main/README.md' \
    org.opencontainers.image.source='https://github.com/it-at-m/zammad-ai' \
    org.opencontainers.image.licenses='MIT' \
    org.opencontainers.image.title='zammad-ai' \
    org.opencontainers.image.description="GenAI-powered agent for Zammad"

# Give permissions to all so random UID can write
# This should be compatible with OpenShift and plain K8s
RUN chown -R root:0 /app && chmod -R g=u /app

USER 1001:0

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"


# Disable tqdm for cleaner logs
ENV TQDM_DISABLE=1
ENV HF_HUB_DISABLE_PROGRESS_BARS=1

# Set tiktoken cache dir
ENV TIKTOKEN_CACHE_DIR="/app/tiktoken_cache"

# Set HuggingFace cache dir
ENV HF_HOME="/app/huggingface_cache"
ENV HUGGINGFACE_HUB_CACHE="/app/huggingface_cache"
ENV TRANSFORMERS_CACHE="/app/huggingface_cache"
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

# Disable python warnings
ENV PYTHONWARNINGS="ignore"

ENV APP_VERSION=${IMAGE_VERSION}

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT ["python", "main.py"]