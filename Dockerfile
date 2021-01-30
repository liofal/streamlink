# Specify base image
FROM python:3.9-alpine as base

# Build dependencies in python
FROM base as builder

# Install every build dependencies in builder image
RUN apk add gcc musl-dev --no-cache
RUN mkdir /install
WORKDIR /install
RUN /usr/local/bin/python -m pip install --upgrade pip
RUN pip install --prefix=/install --upgrade streamlink 
RUN pip install --prefix=/install --upgrade oauth2client
RUN pip install --prefix=/install --upgrade oauthlib
RUN pip install --prefix=/install --upgrade requests_oauthlib

# Run in minimal alpine container with no other dependencies
FROM base as runner
COPY --from=builder /install /usr/local
ADD streamlink-recorder.py /

# Configure entrypoint with environment variables (only user is mandatory)
ENTRYPOINT python ./streamlink-recorder.py -user=${user} -timer=${timer} -quality=${quality} -clientid=${clientid} -clientsecret=${clientsecret} -slackid=${slackid} -gamelist="${gamelist}"