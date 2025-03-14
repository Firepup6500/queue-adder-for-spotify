from os import environ as env
from dotenv import load_dotenv
from quart import Quart, request, redirect
from threading import Thread
from asyncio import run as aRun, sleep
from aiohttp import ClientSession, FormData
from fpsql import asyncSql
from secrets import token_hex
from base64 import b64encode as b64enc, b64decode as b64dec
from urllib.parse import urlencode
from random import shuffle

__p = print


def print(*args, **kwargs):
    kwargs["flush"] = True
    __p(*args, **kwargs)


async def timer() -> None:
    while not await db.get("access_token"):
        await sleep(0.1)
    async with ClientSession(
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "Authorization": "Basic "
            + encode(env["CLIENT_ID"] + ":" + env["CLIENT_SECRET"]),
        }
    ) as session:
        data = FormData()
        data.add_field("refresh_token", await db.get("refresh_token"))
        data.add_field("grant_type", "refresh_token")
        async with await session.post(
            "https://accounts.spotify.com/api/token",
            data=data,
        ) as response:
            json = await response.json()
            await db.set("access_token", json["access_token"])
            if json.get("refresh_token"):
                await db.set("refresh_token", json["refresh_token"])
            await db.set("expires_in", json["expires_in"])
    while True:
        await sleep((await db.get("expires_in")) - 5)
        async with ClientSession(
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "Authorization": "Basic "
                + encode(env["CLIENT_ID"] + ":" + env["CLIENT_SECRET"]),
            }
        ) as session:
            data = FormData()
            data.add_field("refresh_token", await db.get("refresh_token"))
            data.add_field("grant_type", "refresh_token")
            async with await session.post(
                "https://accounts.spotify.com/api/token",
                data=data,
            ) as response:
                json = await response.json()
                await db.set("access_token", json["access_token"])
                if json.get("refresh_token"):
                    await db.set("refresh_token", json["refresh_token"])
                await db.set("expires_in", json["expires_in"])


def encode(string: str) -> str:
    return b64enc(string.encode("utf-8")).decode("utf-8")


def decode(string: str) -> str:
    return b64dec(string.encode("utf-8")).decode("utf-8")


db = asyncSql("database.db")
quartApp = Quart(__name__)
load_dotenv()

for requiredVar in ["CLIENT_ID", "CLIENT_SECRET", "BASE_URL", "USER_ID", "PLAYLIST_ID"]:
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
quartApp.route(
    "/add/",
    methods=["POST", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)


@quartApp.route("/oauth/", methods=["GET"])
async def oauth():
    validStates = await db.get("validStates")
    if not validStates:
        validStates = []
    state = token_hex(16)
    validStates.append(state)
    await db.set("validStates", validStates)
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
    validStates = await db.get("validStates")
    state = request.args.get("state")
    code = request.args.get("code")
    if not state or state not in validStates:
        return '{"ok":false,"error":"invalid_state","http_code":400}', 400
    validStates.remove(state)
    await db.set("validStates", validStates)
    if not code:
        return '{"ok":false,"error":"no_code","http_code":400}', 400
    async with ClientSession(
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "Authorization": "Basic "
            + encode(env["CLIENT_ID"] + ":" + env["CLIENT_SECRET"]),
        }
    ) as session:
        data = FormData()
        data.add_field("code", code)
        data.add_field("redirect_uri", env["BASE_URL"] + "/callback/")
        data.add_field("grant_type", "authorization_code")
        async with await session.post(
            "https://accounts.spotify.com/api/token",
            data=data,
        ) as response:
            json = await response.json()
            if response.status != 200:
                return (
                    f'{{"ok":false,"error":"{json["error"]}","http_code":{response.status}}}',
                    response.status,
                )
            async with ClientSession(
                headers={
                    "Authorization": "Bearer " + json["access_token"],
                }
            ) as session:
                async with await session.get(
                    "https://api.spotify.com/v1/me",
                ) as response2:
                    json2 = {}
                    try:
                        json2 = await response2.json()
                    except:
                        return (
                            '{"ok":false,"error":"spotify_is_malformed","http_code":400}',
                            400,
                        )
                    if json2["id"] != env["USER_ID"]:
                        return '{"ok":false,"error":"wrong_user","http_code":400}', 400
                    await db.set("access_token", json["access_token"])
                    await db.set("refresh_token", json["refresh_token"])
                    await db.set("expires_in", json["expires_in"])
                    return '{"ok":true,"http_code":200}', 200


@quartApp.route("/add/", methods=["GET"])
async def add():
    async with ClientSession(
        headers={
            "Authorization": "Bearer " + await db.get("access_token"),
        }
    ) as session:
        uris = []
        offset = 0
        while offset != -1:
            async with await session.get(
                f"https://api.spotify.com/v1/playlists/{env['PLAYLIST_ID']}/tracks?fields=items.track.uri&limit=50&offset={offset}",
            ) as response:
                json = await response.json()
                for item in json["items"]:
                    uris.append(item["track"]["uri"])
                offset += 50
                if len(json["items"]) < 50:
                    offset = -1
        shuffle(uris)
        for uri in uris:
            async with await session.post(
                f"https://api.spotify.com/v1/me/player/queue?" + urlencode({"uri": uri})
            ) as response:
                if response.status != 200:
                    print(response)
                    return (
                        '{"ok":false,"error":"unknown","http_code":'
                        + str(response.status)
                        + "}",
                        response.status,
                    )
    return '{"ok":true,"http_code":200}', 200


if __name__ == "__main__":
    Thread(target=aRun, args=(timer(),), daemon=True).start()
    quartApp.run(host="0.0.0.0", port=int(env.get("PORT", "65036")))
    print()
