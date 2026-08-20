import json
import urllib.request

URL = "https://reports.exodus-privacy.eu.org/api/trackers"

OUTPUT = "trackers.json"


def download_trackers():

    print("Downloading Exodus tracker database...")

    request = urllib.request.Request(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)

    trackers = data["trackers"]

    print(f"Trackers received: {len(trackers)}")

    with open(
        OUTPUT,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            trackers,
            f,
            indent=4,
            ensure_ascii=False
        )

    print(f"Written to: {OUTPUT}")


if __name__ == "__main__":
    download_trackers()