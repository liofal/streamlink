# Base image with Python
FROM python:3-alpine as base
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

# Set the entrypoint
ENTRYPOINT python ./streamlink-recorder.py -user=${user} -timer=${timer} -quality=${quality} -clientid=${clientid} -clientsecret=${clientsecret} -slackid=${slackid} -gamelist="${gamelist}" -twitchaccountauth=${twitchaccountauth}