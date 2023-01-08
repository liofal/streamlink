"""
This script checks if a user on twitch is currently streaming and 
then records the stream via streamlink
"""
import subprocess
import datetime
import argparse


import json
import os
import re

from threading import Timer
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session

import requests

# enable extra logging
# import logging
# import sys
# log = logging.getLogger('requests_oauthlib')
# log.addHandler(logging.StreamHandler(sys.stdout))
# log.setLevel(logging.DEBUG)

def post_to_slack(message):
    """this function is in charge of the slack notification"""
    if slack_id is None:
        print("slackid is not specified, so disabling slack notification")

    slack_url = f"https://hooks.slack.com/services/{slack_id}"
    slack_data = {'text': message}

    try:
        response = requests.post(
            slack_url, data=json.dumps(slack_data),
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise ValueError(
            f'Request to slack returned an error {response.status_code}, '
            f'the response is:\n{response.text}'
        )
    except Exception as e:
        print(f"Error occurred while sending message to Slack: {e}")

def get_from_twitch(operation):
    """this function encapsulates all get operation to the twitch API and manages authentication"""
    client = BackendApplicationClient(client_id=client_id)
    oauth = OAuth2Session(client=client)
    oauth.fetch_token(
        token_url='https://id.twitch.tv/oauth2/token',
        client_id=client_id,
        client_secret=client_secret,
        include_client_id=True)

    url = 'https://api.twitch.tv/helix/' + operation
    response = oauth.get(
        url,
        headers={
            'Accept': 'application/json',
            'Client-ID': client_id})

    if response.status_code != 200:
        raise ValueError(
            f'Request to twitch returned an error {response.status_code}, '
            f'the response is:\n{response.text}'
        )
    try:
        info = json.loads(response.content)
        # print(json.dumps(info, indent=4, sort_keys=True))
    except Exception as e:
        print(e)
    return info


def check_user(user):
    """this function checks if a user is online"""
    title=""
    status=3
    try:
        info = get_from_twitch('streams?user_login=' + user)
        if len(info['data']) == 0:
            status = 1
        elif game_list != '' and info['data'][0].get("game_id") not in game_list.split(','):
            status = 4
        else:
            title = info['data'][0].get("title")
            status = 0
    except Exception as e:
        print(e)
        status = 3
    return status, title


def loopcheck():
    """this function orchestrate in a loop and will check and trigger download until interrupted"""
    status, title = check_user(user)
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
        filename = f"{user} - {datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S')} - {title}.mp4"
        
        # Remove any character that is not a letter, a digit, a space, or one of these characters: -_.:
        filename = re.sub(r'[^\w\s._:-]', '', filename)
        recorded_filename = os.path.join("./download/", filename)
        
        # start streamlink process
        message=f"recording {user} ..."
        post_to_slack(message)
        print(message)
        run_streamlink(twitch_account_auth, user, quality, recorded_filename)
        message=f"Stream {user} is done. File saved as {filename}. Going back to checking.."
        print(message)
        post_to_slack(message)

        t = Timer(timer, loopcheck)
        t.start()

def run_streamlink(twitch_account_auth, user, quality, recorded_filename):
    command = [
        "streamlink",
        "--twitch-disable-hosting",
        "--retry-max",
        "5",
        "--retry-streams",
        "60",
        f"twitch.tv/{user}",
        quality,
        "-o",
        recorded_filename
    ]
    if twitch_account_auth:
        command.insert(1, f"--twitch-api-header=Authorization=OAuth {twitch_account_auth}")
    subprocess.run(command)

def main():
    """main function parse and check the arguments and will initiate the loop check if valid"""
    global timer, user, quality, client_id, client_secret, slack_id, game_list, twitch_account_auth

    parser = argparse.ArgumentParser()
    parser.add_argument("-timer", type=int, default=240, help="Stream check interval (less than 15s are not recommended)")
    parser.add_argument("-user", required=True, help="Twitch user that we are checking")
    parser.add_argument("-quality", default="720p60,720p,best", help="Recording quality")
    parser.add_argument("-clientid", required=True, help="Your twitch app client id")
    parser.add_argument("-clientsecret", required=True, help="Your twitch app client secret")
    parser.add_argument("-slackid", help="Your slack app client id")
    parser.add_argument("-gamelist", default="", help="The game list to be recorded")
    parser.add_argument("-twitchaccountauth", help="Twitch personal account token. To disable embedded ads")
    args = parser.parse_args()
 
    timer = args.timer
    user = args.user
    quality = args.quality
    slack_id = args.slackid
    game_list = args.gamelist
    twitch_account_auth = args.twitchaccountauth
    client_id = args.clientid
    client_secret = args.clientsecret

    print("Checking for", user, "every", timer, "seconds. Record with", quality, "quality.")
    loopcheck()


if __name__ == "__main__":
    # execute only if run as a script
    main()
