# Context
I was in the search for a twitch stream ripper that would monitor and save streams to my twitch synology folder to watch on plex while I'm unable to watch online.

I could not find an existing image that would respond exactly to my needs so I combined what I could find from few existing projects (see credits here below)

I decided to build it automatically on docker hub to access from my swarm nodes, when I saw many downloads, I decided to document a bit more the project, for my personnal experience and to encourage reusability

Questions, suggestions, requests, reach me out on [![alt text][1.1]][1]

I'm also interested with new projects for automation of daily popular tasks, don't hesitate, I'm waiting for new ideas

# ⚠️ Disclaimer ⚠️
We have renamed the master branch to main for clarity and to follow best practices. Please reconfigure your branch origin with the following commands:

```sh
git branch -m master main
git fetch origin
git branch -u origin/main main
git remote set-head origin -a
```

# Notes

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
## timer
Fill in twitch clientid to interact with twitch API and retrieve status of stream from stream list

    timer=360


## clientid
Fill in twitch clientid to interact with twitch API and retrieve status of stream from stream list

    clientid=xxxxxxxx

## clientsecret
Fill in twitch clientsecret to interact with twitch API and retrieve status of stream from stream list

    clientsecret=xxxxxxxx

## slackid
Fill in slack if you want recod start/stop notification

    slackid=xxxxxxxxx

## oauthtoken
Fill in your OAuth token for Twitch API to authenticate requests. The procedure to collect the OAuth token is described [here](https://streamlink.github.io/cli/plugins/twitch.html) 

    oauthtoken=xxxxxxxx

In order to get the personal OAuth token from Twitch's website which identifies your account, open Twitch.tv in your web browser and after a successful login, open the developer tools by pressing F12 or CTRL+SHIFT+I. Then navigate to the "Console" tab or its equivalent of your web browser and execute the following JavaScript snippet, which reads the value of the auth-token cookie, if it exists:

```javascript
document.cookie.split("; ").find(item=>item.startsWith("auth-token="))?.split("=")[1]
```

# Docker
    docker run -d --rm \
    -v twitch:/app/download \
    -e timer=360 \
    -e user=heromarine \
    -e quality=best \
    -e clientid=XxX \
    -e clientsecret=XxX \
    -e slackid=XxX \
    liofal/streamlink:latest

# Compose

## Startup
To run a test service

    ./docker-compose -f dockerimages/streamlink/docker-compose.yml up -d test

## clientid.env
Specify the clientid.env file using the clientid.env.example delivered

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

3. **Install the Helm Chart:**
    ```sh
    helm install my-streamlink streamlink/streamlink -n streamlink -f /path/to/your/values.yaml
    ```

    Replace `/path/to/your/values.yaml` with the path to your customized `values.yaml` file.

4. **Customize Your `values.yaml`:**
    Edit the `values.yaml` file to configure the deployment according to your needs. Here is an example configuration:
    ```yaml
    image:
      streamlink:
        repository: ghcr.io/liofal
        name: streamlink
        tag: 3.3.2
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

    twitch:
      clientid: "<value_here>"
      clientsecret: "<value_here>"
      oauthtoken: "<value_here>"

    ffmpeg:
      sleeptime: "<sleeptime_value>"
      workdir: "<workdir_value>"

    slack:
      id: "<value_here>"

    telegram:
      bottoken: "<value_here>"
      chatid: "<value_here>"

    nfs:
      server: <server_ip_here>
      path: /<volume>/<folder>
    ```

5. **Upgrade the Helm Release:**
    If you need to apply changes to your deployment, update your `values.yaml` file and run:
    ```sh
    helm upgrade my-streamlink streamlink/streamlink -n streamlink -f /path/to/your/values.yaml
    ```

6. **Uninstall the Helm Release:**
    To remove the deployment, run:
    ```sh
    helm uninstall my-streamlink -n streamlink
    ```

[1.1]: http://i.imgur.com/tXSoThF.png (twitter icon with padding)
[1]: http://www.twitter.com/liofal
