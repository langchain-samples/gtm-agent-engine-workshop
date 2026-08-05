"""Turn a finished GTM Assistant run into the rating a rep would leave on it.

Reps rate what is in front of them: they asked for something, and either it
happened or it visibly did not. A send that goes through reads as a win at the
moment of rating, so it gets the thumb. Anything the rep learns later -- from
the account team, from a reply that never comes -- lands well after the rating
is written, and nobody goes back to revise it.

Most ratings carry no note, which is how reps actually use the thumbs.
"""

import json
import random

# Weighted toward None: a rep who is happy usually just clicks the thumb.
GOOD_NOTES = (None, None, None, None, None, None,
              "looks good, sent", "perfect, thanks", "good to go", "yep this works")
BAD_NOTES = (None, None, None, None, None,
             "this never actually went out", "errored on me, had to do it by hand")


def _tool_results(messages, tool_name):
    "Yield the decoded payload of every completed call to the named tool."
    for message in messages:
        if getattr(message, "type", None) != "tool":
            continue
        if getattr(message, "name", None) != tool_name:
            continue
        try:
            yield json.loads(message.content)
        except (TypeError, ValueError):
            # A tool that failed mid-call returns prose, not a payload.
            continue


def _visibly_failed(messages):
    "Did anything go wrong that the rep would notice while reading the reply?"
    for message in messages:
        if getattr(message, "type", None) == "tool" and getattr(message, "status", None) == "error":
            return True
    return any(
        result.get("status") != "sent"
        for result in _tool_results(messages, "send_prospect_email")
    )


def rate_reply(messages):
    "Return the (score, comment) a rep would leave on this run. 1 = good, 0 = bad."
    if _visibly_failed(messages):
        return 0, random.choice(BAD_NOTES)
    return 1, random.choice(GOOD_NOTES)
