import base64
from io import BytesIO
from pathlib import Path

import requests

##############################
# Custom Vars - Modify these #
##############################
RANKING_FILE = "riitag_most_popular.txt"  # path to the ranking file.
DOWNLOAD_COUNT = 30  # only download the top n images.

AUTO_UPLOAD = True  # If set to True, automatically uploads the images to a Discord application.
OUT_DIR = "assets/"  # Where to save the downloaded images. Can be empty.
ASSET_NAME = "game_{game_id}"  # name of the asset, use {game_id} as placeholder for the game ID.

# DISCORD_* settings require AUTO_UPLOAD to be set to True.
DISCORD_TOKEN = ""
DISCORD_APP_ID = "749633517813628968"  # Application ID to upload the assets to

################################################
# Constants - Don't modify (or do if ur crazy) #
################################################

COVER_URL = "https://art.gametdb.com/{console}/{cover}/{region}/{game}.{ext}"

ASSET_UPLOAD_URL = f"https://discord.com/api/v8/oauth2/applications/{DISCORD_APP_ID}/assets"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:10.0) Gecko/20100101 Firefox/10.0"


##############################
# Code n stuff no modify plz #
##############################

class RiitagGame:
    def __init__(self, game_id, play_count):
        self.game_id: str = game_id
        self.play_count: int = play_count

    @property
    def region(self):
        region_char = self.game_id[3]
        if region_char == "E":
            return "US"
        elif region_char == "J":
            return "JA"
        elif region_char == "K":
            return "KO"
        elif region_char == "W":
            return "TW"
        else:
            return "EN"

    @property
    def console(self):
        code = self.game_id[0]

        # not complete, needs support for console prefixes.
        return "wii" if code in ["R", "S"] or code not in ["A", "B"] else "wiiu"

    @property
    def cover_type(self):
        return "box" if self.console in ["ds", "3ds"] else "cover3D"

    @property
    def img_extension(self):
        return "png" if self.console == "wii" or self.cover_type != "cover" else "jpg"

    @property
    def cover_url(self):
        return COVER_URL.format(
            console=self.console,
            cover=self.cover_type,
            region=self.region,
            game=self.game_id,
            ext=self.img_extension
        )


class DiscordAsset:
    def __init__(self, id, type, name):
        self.id = id
        self.type = type
        self.name = name

    def __eq__(self, other):
        return self.name == other.name if isinstance(other, DiscordAsset) else False

    def remove(self):
        headers = {
            "User-Agent": USER_AGENT,
            "Authorization": DISCORD_TOKEN
        }
        url = f"{ASSET_UPLOAD_URL}/{self.id}"

        r = requests.delete(url, headers=headers)
        if r.status_code == 404:  # already gone? ok then
            return

        r.raise_for_status()


def download_cover(game: RiitagGame):
    r = requests.get(game.cover_url)
    return None if r.status_code != 200 else BytesIO(r.content)


def upload_asset(file, name):
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": DISCORD_TOKEN
    }
    base64_image = base64.b64encode(file.read()).decode('utf-8')
    payload = {
        "image": f"data:image/png;base64,{base64_image}",
        "name": name,
        "type": "1"
    }

    r = requests.post(ASSET_UPLOAD_URL, headers=headers, json=payload)
    r.raise_for_status()

    return DiscordAsset(**r.json())


def get_assets():
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": DISCORD_TOKEN
    }

    r = requests.get(ASSET_UPLOAD_URL, headers=headers)
    r.raise_for_status()

    return [DiscordAsset(**data) for data in r.json()]


def parse_rankings(fp, max_results):
    games = []
    with open(fp) as file:
        for line in file:
            count, game_id = line.split()
            game = RiitagGame(
                play_count=int(count),
                game_id=game_id.strip()
            )
            games.append(game)

    games = sorted(games, key=lambda g: g.play_count, reverse=True)

    return games[:max_results]


def main():
    out_path = Path(OUT_DIR)
    out_path.mkdir(parents=True, exist_ok=True)

    games = parse_rankings(RANKING_FILE, DOWNLOAD_COUNT)
    failed_games = []

    app_assets = get_assets()

    for n, game in enumerate(games):
        print(f"({n + 1}/{DOWNLOAD_COUNT}) Downloading {game.game_id}...", end="\r", flush=True)

        status = "SUCCESS"

        cover = download_cover(game)
        if not cover:
            failed_games.append(game)
            print(f"({n + 1}/{DOWNLOAD_COUNT}) {game.game_id} finished (FAILED)")

            continue

        asset_name = ASSET_NAME.format(game_id=game.game_id).lower()

        if OUT_DIR:
            with open(out_path / f"{asset_name}.{game.img_extension}", "wb+") as file:
                file.write(cover.read())
                cover.seek(0)

        if AUTO_UPLOAD:
            if existing_assets := [
                asset for asset in app_assets if asset.name == asset_name
            ]:
                for num, asset in enumerate(existing_assets):
                    print(f"({n + 1}/{DOWNLOAD_COUNT}) Removing dupe asset {num}/{len(existing_assets)}...",
                          end="\r", flush=True)

                    asset.remove()

                print(" " * 40, end="\r")

            print(f"({n + 1}/{DOWNLOAD_COUNT}) Uploading {game.game_id}...", end="\r", flush=True)

            try:
                upload_asset(cover, asset_name)
            except requests.RequestException as e:
                failed_games.append(game)
                status = "FAILED"

                print(f"ERROR: {e.response.text}")

        print(f"({n + 1}/{DOWNLOAD_COUNT}) {game.game_id} finished ({status})")

    print()
    print(f"A total of {len(games) - len(failed_games)} assets have been processed.")
    if failed_games:
        print("These games failed to upload and may require manual intervention:")
        for game in failed_games:
            print(f"=> {game.game_id} - {game.cover_url}")


if __name__ == '__main__':
    main()
