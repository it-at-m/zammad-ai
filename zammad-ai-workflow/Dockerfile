# Smallest ubi10 image
FROM registry.access.redhat.com/ubi10/ubi-minimal:latest@sha256:44b6115890f31c9dc178a9f0f115d781892bc5e9478860e7f82d445217bc987c

COPY --from=ghcr.io/astral-sh/uv:latest@sha256:78bc42400d77b0678ba95765305c826652ed5431f399257271dda681d0318f03 /uv /uvx /bin/

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

# Set tiktoken cache dir
ENV TIKTOKEN_CACHE_DIR="/app/tiktoken_cache"

# Disable python warnings
ENV PYTHONWARNINGS="ignore"

ENV APP_VERSION=${IMAGE_VERSION}

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT ["python", "main.py"]