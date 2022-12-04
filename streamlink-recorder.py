# This script checks if a user on twitch is currently streaming and then records the stream via streamlink
import subprocess
import datetime
import argparse

import requests
import json
import os

from threading import Timer
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session

## enable extra logging
# import logging
# import sys
# log = logging.getLogger('requests_oauthlib')
# log.addHandler(logging.StreamHandler(sys.stdout))
# log.setLevel(logging.DEBUG)

# Init variables with some default values
timer = 30
user = ""
quality = "best"
client_id = ""
client_secret = ""
token = ""
slack_id = ""
game_list = ""

# Init variables with some default values
def post_to_slack(message):
    if slack_id is None:
        print("slackid is not specified, so disabling slack notification")
        pass

    slack_url = "https://hooks.slack.com/services/" + slack_id
    slack_data = {'text': message}

    response = requests.post(
        slack_url, data=json.dumps(slack_data),
        headers={'Content-Type': 'application/json'},
        timeout=30
    )
    if response.status_code != 200:
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )

# still need to manage token refresh based on expiration
def get_from_twitch(operation):
    client = BackendApplicationClient(client_id=client_id)
    oauth = OAuth2Session(client=client)
    token = oauth.fetch_token(token_url='https://id.twitch.tv/oauth2/token', client_id=client_id, client_secret=client_secret,include_client_id=True)

    url = 'https://api.twitch.tv/helix/' + operation
    response = oauth.get(url,headers={'Accept':'application/json','Client-ID':client_id})

    if response.status_code != 200:
        raise ValueError(
            'Request to twitch returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )
    try:
        info = json.loads(response.content)
        # print(json.dumps(info, indent=4, sort_keys=True))
    except Exception as e:
        print(e)
    return info

def check_user(user):

    try:
        info = get_from_twitch('streams?user_login=' + user )
        if len(info['data']) == 0 :
            status = 1
        elif game_list !='' and info['data'][0].get("game_id") not in game_list.split(','):
                status = 4
        else:
            status = 0
    except Exception as e:
        print(e)
        status = 3
    return status

def loopcheck():
    status = check_user(user)
    if status == 2:
        print("username not found. invalid username?")
        return
    elif status == 3:
        print("unexpected error. maybe try again later")
    elif status == 1:
        print(user, "currently offline, checking again in", timer, "seconds")
    elif status == 4:
        print("unwanted game stream, checking again in", timer, "seconds")
    elif status == 0:
        filename = user + " - " + datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S") + " - " + "title" + ".mp4"
        
        # clean filename from unecessary characters
        filename = "".join(x for x in filename if x.isalnum() or x in [" ", "-", "_", "."])
        recorded_filename = os.path.join("/download/", filename)
        
        # start streamlink process
        post_to_slack("recording " + user+" ...")
        print(user, "recording ... ")
        subprocess.call(["streamlink", "--twitch-disable-hosting", "--retry-max", "5", "--retry-streams", "60", "twitch.tv/" + user, quality, "-o", recorded_filename])
        print("Stream is done. Going back to checking.. ")
        post_to_slack("Stream "+ user +" is done. Going back to checking..")

    t = Timer(timer, loopcheck)
    t.start()

def main():
    global timer
    global user
    global quality
    global client_id
    global client_secret
    global slack_id
    global game_list

    parser = argparse.ArgumentParser()
    parser.add_argument("-timer", help="Stream check interval (less than 15s are not recommended)")
    parser.add_argument("-user", help="Twitch user that we are checking")
    parser.add_argument("-quality", help="Recording quality")
    parser.add_argument("-clientid", help="Your twitch app client id")
    parser.add_argument("-clientsecret", help="Your twitch app client secret")
    parser.add_argument("-slackid", help="Your slack app client id")
    parser.add_argument("-gamelist", help="The game list to be recorded")
    args = parser.parse_args()
 
    if args.timer is not None:
        timer = int(args.timer)
    if args.user is not None:
        user = args.user
    if args.quality is not None:
        quality = args.quality
    if args.slackid is not None:
        slack_id = args.slackid
    if args.gamelist is not None:
        game_list = args.gamelist

    if args.clientid is not None:
        client_id = args.clientid
    if args.clientsecret is not None:
        client_secret = args.clientsecret
    if client_id is None:
        print("Please create a twitch app and set the client id with -clientid [YOUR ID]")
        return
    if client_secret is None:
        print("Please create a twitch app and set the client secret with -clientsecret [YOUR SECRET]")
        return

    print("Checking for", user, "every", timer, "seconds. Record with", quality, "quality.")
    loopcheck()

if __name__ == "__main__":
    # execute only if run as a script
    main()