# Base image with Python
FROM python:3.14.1-alpine3.21@sha256:fd8407cacb1028c803566276ae25eb7c2a00fbaa210a0a5670994f6866e29278 as base
WORKDIR /app

# Builder stage to install build dependencies and Python packages
FROM base as builder
RUN apk add --no-cache gcc musl-dev \
    && pip install --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt 

# Runner stage for the final image
FROM base as runner
COPY --from=builder /install /usr/local
COPY streamlink-recorder.py .
COPY twitch_manager.py .
COPY streamlink_manager.py .
COPY notification_manager.py .

# Uninstall pip, setuptools, and ensurepip
RUN python -m pip uninstall -y pip setuptools \
    && rm -rf /usr/local/lib/python3.*/ensurepip

# Run as a non-root user that matches the compose/NFS owner (1027, group users=100).
# /app stays root-owned and read-only; only /app/download (a volume) is writable.
RUN adduser -D -H -u 1027 -G users -s /sbin/nologin streamlink \
    && mkdir -p /app/download \
    && chown 1027:100 /app/download

# Works with a read-only root filesystem: no bytecode writes, and the streamlink
# cache goes under /tmp (tmpfs/emptyDir) instead of $HOME.
ENV PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/tmp/.cache

# Numeric so Kubernetes runAsNonRoot can verify it.
USER 1027:100

# Set the entrypoint without expanding secrets into process arguments.
ENTRYPOINT ["python", "./streamlink-recorder.py"]
