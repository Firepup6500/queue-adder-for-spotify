from os import environ as env
from dotenv import load_dotenv
from quart import Quart, request, redirect
from threading import Thread
from asyncio import run as aRun
from async_timeout import timeout
from aiohttp import ClientSession
from urllib.parse import unquote, urlencode
from fpsql import asyncSql
from traceback import format_exc
from secrets import token_hex

__p = print


def print(*args, **kwargs):
    kwargs["flush"] = True
    __p(*args, **kwargs)


db = asyncSql("database.db")
quartApp = Quart(__name__)
load_dotenv()

for requiredVar in ["CLIENT_ID", "CLIENT_SECRET", "BASE_URL"]:
    if not env.get(requiredVar):
        raise ValueError(
            f'Missing required environment variable "{requiredVar}". Please create a .env file in the same directory as this script and define the missing variable.'
        )


@quartApp.route(
    "/callback/",
    methods=["POST", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)
async def invalid():
    return '{"ok":false,"error":"method_not_allowed","http_code":405}', 405


quartApp.route(
    "/oauth/",
    methods=["POST", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)


global validStates
validStates = []


@quartApp.route("/oauth/", methods=["GET"])
async def oauth():
    global validStates
    state = token_hex(16)
    validStates.append(state)
    return redirect(
        "https://accounts.spotify.com/authorize?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": env["CLIENT_ID"],
                "scope": "user-modify-playback-state playlist-read-private",
                "redirect_uri": env["BASE_URL"] + "/callback/",
                "state": state,
            }
        )
    )


@quartApp.route("/callback/", methods=["GET"])
async def callback():
    print(request.args)
    return "", 200


if __name__ == "__main__":
    quartApp.run(host="0.0.0.0", port=int(env.get("PORT", "65036")))
    print()
