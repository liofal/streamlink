# ⚠️ Disclaimer ⚠️
We have renamed the master branch to main for clarity and to follow best practices. Please reconfigure your branch origin with the following commands:

# Context
I was in the search for a twitch stream ripper that would monitor and save streams to my twitch synology folder to watch on plex while I'm unable to watch online.

I could not find an existing image that would respond exactly to my needs so I combined what I could find from few existing projects (see credits here below)

I decided to build it automatically on docker hub to access from my swarm nodes, when I saw many downloads, I decided to document a bit more the project, for my personnal experience and to encourage reusability

Questions, suggestions, requests, reach me out on [![alt text][1.1]][1]

I'm also interested with new projects for automation of daily popular tasks, don't hesitate, I'm waiting for new ideas


```sh
git branch -m master main
git fetch origin
git branch -u origin/main main
git remote set-head origin -a
```

# Notes

## 4.0.0
Update dependency streamlink to v8.0.0
Removed deprecated `twitch-disable-hosting` and `twitch-disable-ads` options (handled automatically by Streamlink 8.x)

## 3.3.4
Update dependency streamlink to v7.1.3

## 3.3.3 
Update dependency streamlink to v7.1.2
Fix filename sanitization to handle reserved characters

## 3.3.2
Refactor filename generation and add support for dynamic stream extensions in StreamlinkManager, in reference to improvement suggestion by [thematuu](https://github.com/thematuu) in [PR20](https://github.com/liofal/streamlink/pull/20)

Add sidecar container for ffmpeg converstion to mp4 of .ts files.

## 3.3.1
Bump up versions dependencies.
* requests==2.32.3
* streamlink==7.1.1
* twitchAPI==4.4.0

And activate renovate for automatic dependencies upgrade, be aware of that setup and use automatic trigger of "latest" dockerimage replacement.

## 3.2.0
Added support for optional OAuth token parameter to authenticate Twitch API requests.

## 3.1.0 - 3.1.1
Automatic build and deployment pipeline to both ghcr and docker hub.
With tag versioning and latest tagging.
Remove broken support for oauth twitch token, will soon migrate to new model

## 3.0.0
Introduced Twitch API integration for improved stream monitoring.

Added support for notification via Telegram, as requested in [issue #1](https://github.com/liofal/streamlink/issues/1).

Refactored the notification system to support multiple platforms, including Slack and Telegram.

Major code refactor for better modularity and readability, including the use of classes for Twitch, Streamlink, and notification management.

## 2.1.0
Migration to ghcr.io, please adapt your links!

github actions automatic build with kaniko

Adapt for helm deployment

## 2.0.2 - 2.0.3
solved bug of env args being ignored [#10](https://github.com/liofal/streamlink/issues/10)
thanks to [too-many-bees](https://github.com/too-many-bees) for raising it up.

## 2.0.1
solved bug of missing loop issue [#6](https://github.com/liofal/streamlink/issues/6)
thanks to [too-many-bees](https://github.com/too-many-bees) for raising it up.

## 2.0
major refactoring and improvements to the code, respect standards and best practices 

parse title stream and add to filename

added contribution from [zerobell-lee](https://github.com/zerobell-lee) to disable ads by authenticating as a twitch user 

## 1.9.0 - 1.9.1
Move to python 3.11
Various improvements to project, cleanup and dependencies management

## 1.8.0 - 1.8.5
Full rework with support of OAuth2 token management
Review of helix twitch operation and simplification of the flow

Upgrade python python:3.9.1-alpine3.12

# Credits
Originally inspired from the work of the people here below.
Thanks to those people.

https://github.com/Neolysion/Twitch-Recorder/blob/master/check.py

https://www.junian.net/2017/01/how-to-record-twitch-streams.html

I cleaned up and adapted following my requirements and added a slack integration

All rights are reserved to the original script owners, it has been now mostly reworked from scratch nevertheless will remove code if requested.

# Quality
Quality is specified within the stream, any twitch quality specified existing for the stream can be defined

Keywords can always be used
* best
* worst

# Variables

Environment variables are primarily used for Docker deployments. For Kubernetes/Helm deployments, configuration is managed with `values.yaml`, ConfigMaps, and Kubernetes Secrets.

Existing lowercase variable names remain supported for compatibility. New deployments may use the uppercase aliases below.

| Purpose | Existing name | Preferred alias |
| --- | --- | --- |
| Twitch user to monitor | `user` | `TWITCH_USER` |
| Check interval in seconds | `timer` | `TIMER` |
| Recording quality | `quality` | `STREAM_QUALITY` |
| Twitch Helix client ID | `clientid` | `TWITCH_CLIENT_ID` |
| Twitch Helix client secret | `clientsecret` | `TWITCH_CLIENT_SECRET` |
| Streamlink Twitch playback auth token | `oauthtoken` | `TWITCH_AUTH_TOKEN` or `TWITCH_OAUTH_TOKEN` |
| Slack webhook path/ID | `slackid` | `SLACK_ID` |
| Telegram bot token | `telegrambottoken` | `TELEGRAM_BOT_TOKEN` |
| Telegram chat ID | `telegramchatid` | `TELEGRAM_CHAT_ID` |
| Comma-separated Twitch game IDs to record | `gamelist` | `GAME_LIST` |

## Twitch credentials and playback auth

This project uses two different Twitch credential types:

1. **Twitch Developer Portal credentials**: `clientid` / `clientsecret` or `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET`.
   These are used by this app to call Twitch Helix and check whether the configured streamer is live.
2. **Streamlink Twitch playback auth token**: `oauthtoken`, `TWITCH_AUTH_TOKEN`, or `TWITCH_OAUTH_TOKEN`.
   This is the `auth-token` browser cookie from a logged-in Twitch web session, passed to Streamlink as `Authorization=OAuth <token>` for playback requests.

The playback auth token is **not** the same thing as a normal Twitch Developer Portal OAuth refresh-token flow. Streamlink's Twitch playback authentication currently relies on the browser `auth-token` cookie.

The playback token is optional. Omit it when unauthenticated recording of public streams works for your use case. Configure it only when the Twitch stream/VOD playback you need requires authenticated browser access.

### Twitch auth-token security caveats

Treat the browser `auth-token` like an account secret:

- Do not paste it into GitHub issues, chat, screenshots, or logs.
- Do not commit real values to this repository.
- Prefer env files, Docker secrets, or Kubernetes Secrets over inline terminal commands.
- Logging out of Twitch may not immediately revoke previously issued tokens.
- If a token may have leaked, use Twitch account security settings, password rotation, and "sign out everywhere" style controls to invalidate active sessions where available.

### Getting or renewing the playback auth token

1. Log in to Twitch in a browser as the account you want Streamlink to use for playback.
2. Open the browser developer tools and inspect cookies for `twitch.tv`.
3. Copy the value of the `auth-token` cookie only.
4. Store it as `oauthtoken`, `TWITCH_AUTH_TOKEN`, or `TWITCH_OAUTH_TOKEN` in your deployment secret store.
5. Restart or roll out the recorder so it receives the new value.

Avoid pasting real tokens directly into shell commands on shared systems because they may be saved in shell history or terminal logs.

# Docker

For Docker, prefer an env file instead of inline `-e` flags for secrets:

```env
# clientid.env - keep this file out of git
TWITCH_CLIENT_ID=xxxxxxxx
TWITCH_CLIENT_SECRET=xxxxxxxx
TWITCH_AUTH_TOKEN=xxxxxxxx # optional browser auth-token for Streamlink playback
SLACK_ID=xxxxxxxxx
TELEGRAM_BOT_TOKEN=xxxxxxxxx
TELEGRAM_CHAT_ID=xxxxxxxxx
```

```sh
docker run -d --rm \
  --env-file clientid.env \
  -v twitch:/app/download \
  -e TIMER=360 \
  -e TWITCH_USER=heromarine \
  -e STREAM_QUALITY=best \
  ghcr.io/liofal/streamlink:latest
```

Existing lowercase env files continue to work:

```env
clientid=xxxxxxxx
clientsecret=xxxxxxxx
oauthtoken=xxxxxxxx
```

# Compose

## Startup
To run a test service

    ./docker-compose -f dockerimages/streamlink/docker-compose.yml up -d test

## clientid.env
Specify credentials using the `clientid.env.example` file as a template. Keep real `clientid.env` files out of git.

To renew a Twitch playback auth token in Docker Compose:

1. Update `oauthtoken`, `TWITCH_AUTH_TOKEN`, or `TWITCH_OAUTH_TOKEN` in your local env file.
2. Restart the recorder container with `docker compose up -d` or your normal deployment command.
3. Do not paste the token into issue reports or logs.

## default.env
you can specify the default for compose here

# Volume
    /app/download 

_**Warning:** The folder does not exist in the container and need te be created as a volume in order to be accessed from outside your container, you should map it if you want to access it_

## FFmpeg Conversion

The `docker-compose.yml` file includes an FFmpeg service that automatically converts TS container files to MP4. The FFmpeg service is configured to run periodically and process files in the `/app/download` directory.

- The `SLEEPTIME` environment variable defines the interval (in seconds) between conversion checks. By default, it is set to 600 seconds (10 minutes).
- The `WORKDIR` environment variable specifies the directory where the TS files are located and where the converted MP4 files will be saved.

To customize the FFmpeg conversion settings, you can modify the environment variables in the `docker-compose.yml` file.

# Kubernetes Deployment with Helm

To deploy this project on Kubernetes using Helm, follow these steps:

1. **Create the Namespace:**
    ```sh
    kubectl create namespace streamlink
    ```

2. **Add the Helm Repository:**
    ```sh
    helm repo add streamlink https://github.com/liofal/streamlink/kube/charts
    helm repo update
    ```

3. **Prepare the Shared Secret:**
    Before installing the chart, you must create a single, shared Kubernetes Secret containing the necessary API tokens and IDs for all your streamlink instances. The chart includes an example manifest at `kube/charts/secret.example.yaml`.

    Kubernetes Secret `data` values are base64 encoded, but base64 is **not encryption**. Do not commit real Secret manifests to git.

    For a copy/paste-safe workflow that avoids writing secrets into shell history, put real values in a local env file that is outside git, restrict its permissions, and generate the Secret from that file:

    ```sh
    install -m 600 /dev/null ./streamlink-secrets.env
    $EDITOR ./streamlink-secrets.env
    kubectl create secret generic streamlink-secrets \
      --from-env-file=./streamlink-secrets.env \
      --namespace streamlink \
      --dry-run=client \
      -o yaml | kubectl apply -f -
    ```

    Example `streamlink-secrets.env` keys:

    ```env
    clientid=xxxxxxxx
    clientsecret=xxxxxxxx
    oauthtoken=xxxxxxxx # optional browser auth-token for Streamlink playback
    slackid=xxxxxxxxx
    telegrambottoken=xxxxxxxxx
    telegramchatid=xxxxxxxxx
    ```

    To renew the Twitch playback auth token in Kubernetes:

    1. Update `oauthtoken` in your local secret env file.
    2. Re-run the `kubectl create secret generic ... --dry-run=client -o yaml | kubectl apply -f -` command above.
    3. Roll out or restart the recorder deployment so the pod receives the updated Secret value.

    If you prefer a manifest workflow, copy `kube/charts/secret.example.yaml` outside the repository, replace the placeholders, apply it with `kubectl apply -f`, and keep the real manifest out of git.

4. **Customize Your `values.yaml`:**
    Create a `values.yaml` file (or use an existing one) for each streamlink instance you want to deploy. Ensure the `secretName` field is set to the name of the shared Secret you created in the previous step (e.g., `streamlink-secrets`). Here is an example configuration for one instance:
    ```yaml
    image:
      streamlink:
        repository: ghcr.io/liofal
        name: streamlink
        tag: 3.3.4
        pullPolicy: Always
      ffmpeg: 
        repository: ghcr.io/liofal
        name: ffmpeg6
        tag: 1.0.0
        pullPolicy: Always

    streamer:
      name: "<name_here>"
      twitchName: "<twitch_name_here>"
      quality: "best"
      timer: 120

    # Name of the Kubernetes Secret containing sensitive tokens.
    # This should point to the single, shared Secret created in Step 3.
    secretName: "streamlink-secrets" # Default name for the shared secret

    ffmpeg:
      sleeptime: "<sleeptime_value>"
      workdir: "<workdir_value>"

    nfs:
      server: <server_ip_here>
      path: /<volume>/<folder>
    ```

5. **Install the Helm Chart:**
    ```sh
    helm install my-streamlink streamlink/streamlink -n streamlink -f /path/to/your/values.yaml
    ```
    Replace `/path/to/your/values.yaml` with the path to your customized `values.yaml` file.

6. **Upgrade the Helm Release:**
    If you need to apply changes to your deployment, ensure your Secret is up-to-date, update your `values.yaml` file if necessary, and run:
    ```sh
    helm upgrade my-streamlink streamlink/streamlink -n streamlink -f /path/to/your/values.yaml
    ```

7. **Uninstall the Helm Release:**
    To remove the deployment (this does not remove the Secret):
    ```sh
    helm uninstall my-streamlink -n streamlink
    ```

[1.1]: http://i.imgur.com/tXSoThF.png (twitter icon with padding)
[1]: http://www.twitter.com/liofal
