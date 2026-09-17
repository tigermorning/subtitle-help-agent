# -*- coding: utf-8 -*-
"""넷플릭스 파트너헬프 공개 글을 Help Center API로 받아 sources/raw/에 둔다(저장소 제외).

    python sources/fetch_netflix.py          # 목록 전부
    python sources/fetch_netflix.py 216001127

받은 JSON은 sources/html2md.py가 읽을 수 있는 마크다운으로도 바꿔 둔다.
"""
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
RAW = HERE / "raw"
API = "https://partnerhelp.netflixstudios.com/api/v2/help_center/en-us/articles/{}.json"


def article_ids():
    for line in (HERE / "netflix_articles.txt").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            yield line.split()[0]


def fetch(aid):
    req = urllib.request.Request(API.format(aid), headers={"User-Agent": "subtitle-help-agent"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    (RAW / f"netflix-{aid}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data["article"]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    RAW.mkdir(exist_ok=True)
    sys.path.insert(0, str(HERE))
    from html2md import convert
    for aid in sys.argv[1:] or list(article_ids()):
        a = fetch(aid)
        convert(aid)
        print(aid, a["edited_at"][:10], a["title"])
