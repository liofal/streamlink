# Specify base image
FROM python:3.8.2-alpine3.11 as base

# Build dependencies in python
FROM base as builder

# Install every build dependencies in builder image
RUN apk add gcc musl-dev --no-cache
RUN mkdir /install
WORKDIR /install
RUN pip install --upgrade pip
RUN pip install --install-option="--prefix=/install" --upgrade streamlink google-api-python-client oauth2client

# Run in minimal alpine container with no other dependencies
FROM base as runner
COPY --from=builder /install /usr/local
ADD streamlink-recorder.py /

# Configure entrypoint with environment variables (only user is mandatory)
ENTRYPOINT python ./streamlink-recorder.py -user=${user} -timer=${timer} -quality=${quality} -clientid=${clientid} -slackid=${slackid} -gamelist="${gamelist}"