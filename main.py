# pylint: disable=missing-function-docstring,missing-module-docstring
from os import environ as env
from threading import Thread
from asyncio import run as aRun, sleep
from secrets import token_hex
from base64 import b64encode as b64enc, b64decode as b64dec
from urllib.parse import urlencode
from random import shuffle
from re import match
from aiohttp import ClientSession, FormData
from aiohttp.client_exceptions import ContentTypeError
from fpsql import asyncSql
from dotenv import load_dotenv
from quart import Quart, request, redirect
from quart_auth import (
    AuthUser,
    current_user,
    login_required,
    login_user,
    logout_user,
    QuartAuth,
    Unauthorized,
)

# pylint: disable=used-before-assignment,redefined-builtin
__p = print


def print(*args, **kwargs):
    kwargs["flush"] = True
    __p(*args, **kwargs)


# pylint: enable=used-before-assignment,redefined-builtin


async def timer(userid: str) -> None:
    userData = await db.get(userid)
    async with ClientSession(
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "Authorization": "Basic "
            + encode(env["CLIENT_ID"] + ":" + env["CLIENT_SECRET"]),
        }
    ) as session:
        data = FormData()
        data.add_field("refresh_token", userData["refresh_token"])
        data.add_field("grant_type", "refresh_token")
        async with await session.post(
            "https://accounts.spotify.com/api/token",
            data=data,
        ) as response:
            json = await response.json()
            userData["access_token"] = json["access_token"]
            if json.get("refresh_token"):
                userData["refresh_token"] = json["refresh_token"]
            userData["expires_in"] = json["expires_in"]
            await db.set(userid, userData)
    while True:
        await sleep(userData["expires_in"] - 5)
        userData = await db.get(
            userid
        )  # A user authing again might break things, re-sync with their data here
        async with ClientSession(
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "Authorization": "Basic "
                + encode(env["CLIENT_ID"] + ":" + env["CLIENT_SECRET"]),
            }
        ) as session:
            data = FormData()
            data.add_field("refresh_token", userData["refresh_token"])
            data.add_field("grant_type", "refresh_token")
            async with await session.post(
                "https://accounts.spotify.com/api/token",
                data=data,
            ) as response:
                json = await response.json()
                userData["access_token"] = json["access_token"]
                if json.get("refresh_token"):
                    userData["refresh_token"] = json["refresh_token"]
                userData["expires_in"] = json["expires_in"]
                await db.set(userid, userData)


def encode(string: str) -> str:
    return b64enc(string.encode("utf-8")).decode("utf-8")


def decode(string: str) -> str:
    return b64dec(string.encode("utf-8")).decode("utf-8")


def isBase62(string: str) -> bool:
    return match("^[A-Za-z0-9]+$", string)


db = asyncSql("database.db")
quartApp = Quart(__name__)
load_dotenv()

for requiredVar in ["CLIENT_ID", "CLIENT_SECRET", "BASE_URL", "AUTH_SECRET_KEY"]:
    if not env.get(requiredVar):
        raise ValueError(
            f'Missing required environment variable "{requiredVar}". Please create a .env file in the same directory as this script and define the missing variable.'
        )

quartApp.secret_key = env["AUTH_SECRET_KEY"]
QuartAuth(quartApp, cookie_name="spotify-queue-adder_AUTH")


@quartApp.route(
    "/callback/",
    methods=["POST", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)
async def invalid():
    return (
        '{"ok":false,"error":"method_not_allowed","http_code":405}',
        405,
        {"Content-Type": "application/json"},
    )


quartApp.route(
    "/oauth/",
    methods=["POST", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)
quartApp.route(
    "/add/",
    methods=["GET", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)
quartApp.route(
    "/settings/",
    methods=["GET", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)
quartApp.route(
    "/",
    methods=["POST", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)
quartApp.route(
    "/logout/",
    methods=["POST", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)


@quartApp.errorhandler(Unauthorized)
async def redirect_to_login(*_):
    return redirect("oauth")


@quartApp.route("/logout/", methods=["GET"])
async def logout():
    logout_user()
    return '{"ok":true,"http_code":200}', 200, {"Content-Type": "application/json"}


@quartApp.route("/", methods=["GET"])
@login_required
async def dashboard():
    # pylint: disable=line-too-long
    userData = await db.get(current_user.auth_id)
    playlist_id = userData.get("playlist_id", "")
    playlistElement = "<p>No playlist configured! Please set one below</p>"
    if playlist_id:
        playlistElement = f'<iframe style="border-radius:12px" src="https://open.spotify.com/embed/playlist/{playlist_id}" width="100%" height="500" frameborder="0" allow="encrypted-media; fullscreen; picture-in-picture" loading="lazy"></iframe>'
    return (
        f'<!DOCTYPE html><html><head><title>Queue Adder For Spotify</title><style>*{{color-scheme:dark}}</style><script>function add_playlist(){{window.scrollTo(0,0);document.getElementById("add").disabled=true;document.getElementById("status").innerText="Adding songs to queue, please be patient...";fetch("add/",{{method:"POST"}}).then(response=>response.json()).then(data=>{{if(data.ok){{document.getElementById("status").innerText=`Idle - ${{data.fail_count}} tracks failed to add to the queue`;document.getElementById("add").disabled=false}}else{{document.getElementById("status").innerText=`An error occured: ${{data.error}}`}}}}).catch(error=>document.getElementById("status").innerText="An Unknown Fatal Error Occured");}}</script></head><body><h1>Queue Adder For Spotify Dashboard</h1><h3>Current Status: <span id=status>Idle</span><h2>Hi {userData["display_name"]}!</h2></h3><p>Configured Playlist:</p>{playlistElement}<button {"disabled=true " if not playlist_id else ""}onclick="add_playlist();" id=add>Add configured playlist to queue</button><br/><button onclick="location.href = \'logout/\';">Logout</button><h2>Settings</h2><p id="form-error" style="color:red"></p><form action="settings/" method="post"><label for="playlist_id">Playlist ID (or URL): </label><input name="playlist_id" id="playlist_id" value="{playlist_id}"><br/><label for="display_name">Display Name: </label><input name="display_name" id="display_name" value="{userData["display_name"]}"><br/><button>Submit</button><br/><p style="color:yellow">Warning! Display name will be overwritten with the value from spotify if you log out and back in!</p></form></body></html>',
        200,
    )


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
                "show_dialog": True,
            }
        )
    )


@quartApp.route("/callback/", methods=["GET"])
async def callback():
    validStates = await db.get("validStates")
    state = request.args.get("state")
    code = request.args.get("code")
    if not state or state not in validStates:
        return (
            '{"ok":false,"error":"invalid_state","http_code":400}',
            400,
            {"Content-Type": "application/json"},
        )
    validStates.remove(state)
    await db.set("validStates", validStates)
    if not code:
        return (
            '{"ok":false,"error":"no_code","http_code":400}',
            400,
            {"Content-Type": "application/json"},
        )
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
                    {"Content-Type": "application/json"},
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
                    except ContentTypeError:
                        return (
                            '{"ok":false,"error":"spotify_is_malformed","message":"Contact the app owner, their app is likely in development mode and requires manually adding users to the app config","http_code":400}',
                            400,
                            {"Content-Type": "application/json"},
                        )
                    newUser = False
                    users = await db.get("users")
                    userData = {}
                    if json2["id"] not in users:
                        newUser = True
                        users.append(json2["id"])
                        await db.set("users", users)
                    else:
                        userData = await db.get(json2["id"])
                    userData["access_token"] = json["access_token"]
                    if json.get("refresh_token"):
                        userData["refresh_token"] = json["refresh_token"]
                    userData["expires_in"] = json["expires_in"]
                    userData["display_name"] = (
                        json2["display_name"]
                        if json2.get("display_name")
                        else json2["id"]
                    )
                    await db.set(json2["id"], userData)
                    login_user(AuthUser(json2["id"]))
                    if newUser:
                        Thread(
                            target=aRun, args=(timer(json2["id"]),), daemon=True
                        ).start()
                    return redirect("..")


@quartApp.route("/add/", methods=["POST"])
async def add():
    if not current_user.auth_id:
        return (
            '{"ok":false,"error":"unauthorized","http_code":401}',
            401,
            {"Content-Type": "application/json"},
        )
    userData = await db.get(current_user.auth_id)
    if not userData["playlist_id"]:
        return (
            '{"ok":false,"error":"no_playlist_id","http_code":400}',
            400,
            {"Content-Type": "application/json"},
        )

    async with ClientSession(
        headers={
            "Authorization": "Bearer " + userData["access_token"],
        }
    ) as session:
        uris = []
        offset = 0
        while offset != -1:
            async with await session.get(
                f"https://api.spotify.com/v1/playlists/{userData['playlist_id']}/tracks?fields=items.track.uri&limit=50&offset={offset}",
            ) as response:
                json = {}
                try:
                    json = await response.json()
                except ContentTypeError:
                    return (
                        '{"ok":false,"error":"spotify_is_malformed","message":"!! THIS STATE SHOULD BE IMPOSSIBLE !! Contact the app owner, their app is likely in development mode and requires manually adding users to the app config","http_code":400}',
                        400,
                        {"Content-Type": "application/json"},
                    )
                for item in json["items"]:
                    uris.append(item["track"]["uri"])
                offset += 50
                if len(json["items"]) < 50:
                    offset = -1
        shuffle(uris)
        fail_count = 0
        for uri in uris:
            async with await session.post(
                "https://api.spotify.com/v1/me/player/queue?" + urlencode({"uri": uri})
            ) as response:
                if response.status != 200:
                    print(response)
                    try:
                        json = await response.json()
                        print(json)
                        if json.get("error") and json["error"].get("status") == 403:
                            return (
                                '{"ok":false,"error":"spotify_premium_required","http_code":403}',
                                403,
                            )
                        if json.get("error") and json["error"].get("status") == 404:
                            return (
                                '{"ok":false,"error":"spotify_is_not_playing","http_code":404}',
                                404,
                            )
                    except ContentTypeError:
                        print(await response.get_data())
                    fail_count += 1
    return (
        f'{{"ok":true,"fail_count":{fail_count},"http_code":200}}',
        200,
        {"Content-Type": "application/json"},
    )


@quartApp.route("/settings/", methods=["POST"])
async def settings():
    if not current_user.auth_id:
        return (
            '{"ok":false,"error":"unauthorized","http_code":401}',
            401,
            {"Content-Type": "application/json"},
        )
    form = await request.form
    display_name = form.get("display_name")
    playlist_id = form.get("playlist_id")
    if not display_name:
        return (
            '{"ok":false,"error":"no_display_name","http_code":400}',
            400,
            {"Content-Type": "application/json"},
        )
    if not playlist_id:
        return (
            '{"ok":false,"error":"no_playlist_id","http_code":400}',
            400,
            {"Content-Type": "application/json"},
        )
    if match(
        "^https://open\\.spotify\\.com/playlist/[A-Za-z0-9]+(\\?.+)?$", playlist_id
    ):
        playlist_id = playlist_id.split("/")[4].split("?")[0]
    if not isBase62(playlist_id):
        return (
            '{"ok":false,"error":"playlist_id_must_be_base_62","http_code":400}',
            400,
            {"Content-Type": "application/json"},
        )
    if not isBase62(display_name):
        return (
            '{"ok":false,"error":"display_name_must_be_base_62","http_code":400}',
            400,
            {"Content-Type": "application/json"},
        )
    userData = await db.get(current_user.auth_id)
    userData["playlist_id"] = playlist_id
    userData["display_name"] = display_name
    await db.set(current_user.auth_id, userData)
    return redirect("..")


if __name__ == "__main__":
    try:
        for userid in aRun(db.get("users")):
            Thread(target=aRun, args=(timer(userid),), daemon=True).start()
    except TypeError:
        print("Database must not have been initalized, initalizing now.")
        aRun(db.set("users", []))
    quartApp.run(host="0.0.0.0", port=int(env.get("PORT", "65036")))
    print()
