# Specify base image
FROM python:3.11-alpine3.16 as base

# Build dependencies in python
FROM base as builder

# Install every build dependencies in builder image
RUN apk add gcc musl-dev --no-cache
RUN mkdir /install
WORKDIR /install
RUN /usr/local/bin/python -m pip install --upgrade pip

# install dependencies and build
ADD requirements.txt /install
RUN pip install --prefix=/install -r requirements.txt 

# Run in minimal alpine container with no other dependencies
FROM base as runner
COPY --from=builder /install /usr/local
ADD streamlink-recorder.py /

# Configure entrypoint with environment variables (only user is mandatory)
ENTRYPOINT python ./streamlink-recorder.py -user=${user} -timer=${timer} -quality=${quality} -clientid=${clientid} -clientsecret=${clientsecret} -slackid=${slackid} -gamelist="${gamelist}" -twitchaccountauth=${twitchaccountauth}
