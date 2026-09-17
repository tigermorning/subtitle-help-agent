# -*- coding: utf-8 -*-
"""sources/raw/netflix-<글번호>.json 본문 HTML을 읽을 수 있는 마크다운으로 바꾼다."""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

RAW = Path(__file__).parent / "raw"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("p", "br", "tr", "div"):
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_data(self, data):
        self.out.append(data)


def convert(aid):
    a = json.loads((RAW / f"netflix-{aid}.json").read_text(encoding="utf-8"))["article"]
    p = _Text()
    p.feed(a["body"] or "")
    text = re.sub(r"[ \t\xa0]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    (RAW / f"netflix-{aid}.md").write_text(
        f"# {a['title']}\n\nsource: {a['html_url']}\nedited_at: {a['edited_at']}\n\n{text}",
        encoding="utf-8")


if __name__ == "__main__":
    for aid in sys.argv[1:]:
        convert(aid)
