#!/usr/bin/env python3
import json
import os
import urllib.request


def load_env(path=".env"):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


def es(method, path, body=None):
    base = os.environ["ELASTICSEARCH_URL"].rstrip("/")
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Authorization": f"ApiKey {os.environ['ELASTICSEARCH_API_KEY']}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    load_env()
    index = f"{os.environ['ELASTICSEARCH_INDEX_PREFIX']}-firms"
    count = es("GET", f"/{index}/_count")
    nearby = es(
        "POST",
        f"/{index}/_search",
        {
            "size": 5,
            "sort": [{"acquired_at": "desc"}],
            "query": {
                "bool": {
                    "filter": [
                        {
                            "geo_distance": {
                                "distance": "250km",
                                "location": {"lat": 49.2827, "lon": -123.1207},
                            }
                        }
                    ]
                }
            },
            "_source": ["source", "acquired_at", "latitude", "longitude", "confidence", "frp"],
        },
    )
    print(json.dumps({"index": index, "count": count["count"], "near_vancouver_hits": nearby["hits"]["total"]}, indent=2))


if __name__ == "__main__":
    main()

