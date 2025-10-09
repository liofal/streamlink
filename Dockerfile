# Base image with Python
FROM python:3.14.0-alpine3.21 as base
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

# Set the entrypoint
ENTRYPOINT python ./streamlink-recorder.py -user=${user} -timer=${timer} -quality=${quality} -clientid=${clientid} -clientsecret=${clientsecret} -slackid=${slackid} -gamelist="${gamelist}" -telegramchatid=${telegramchatid} -telegrambottoken=${telegrambottoken} -oauthtoken=${oauthtoken}
