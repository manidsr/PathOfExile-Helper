"""Discord bot sender. UI events cross threads only through the caller's queue."""
import math
import re
import time
import requests


def validate(channel, token, message, minutes):
    if not re.fullmatch(r'[0-9]{17,20}', channel):
        raise ValueError("Enter a Discord channel ID (17–20 digits).")
    if not token.strip():
        raise ValueError("Enter your sender bot token.")
    if not message.strip() or len(message) > 2000:
        raise ValueError("Write a message between 1 and 2,000 characters.")
    if not minutes.isdecimal() or not 1 <= int(minutes) <= 10080:
        raise ValueError("Choose a repeat interval between 1 and 10,080 minutes.")


def run(channel, token, message, minutes, repeat, stop, report, post=requests.post):
    try:
        while not stop.is_set():
            response = post(
                f"https://discord.com/api/v10/channels/{channel}/messages",
                headers={"Authorization": f"Bot {token}"},
                json={"content": message, "allowed_mentions": {"parse": []}},
                timeout=(5, 15), allow_redirects=False,
            )
            if response.status_code == 429:
                delay = float(response.json()["retry_after"])
                if not math.isfinite(delay) or delay < 0 or delay > 86400:
                    raise ValueError()
                report(f"Rate limited. Retrying in {math.ceil(delay)} seconds.")
                stop.wait(max(1, delay))
                continue
            if not response.ok or not 200 <= response.status_code < 300:
                hints = {401: "Check the bot token.", 403: "Check the bot’s channel permissions.",
                         404: "Check the channel ID and bot membership."}
                report(f"Discord returned {response.status_code}. " + hints.get(response.status_code, "Check the destination and try again."))
                return
            sent = time.strftime("%H:%M:%S")
            report(f"Sent at {sent}." + (f" Repeating every {minutes} min." if repeat else ""))
            if not repeat or stop.wait(int(minutes) * 60):
                return
    except requests.RequestException:
        report("Connection interrupted. Check the channel before retrying.")
    except (ValueError, KeyError, TypeError):
        report("Discord returned an unreadable retry interval.")
