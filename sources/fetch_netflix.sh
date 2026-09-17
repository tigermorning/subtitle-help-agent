#!/bin/sh
# 넷플릭스 파트너헬프 공개 글을 Help Center API로 받는다. 결과는 sources/raw/ (저장소 제외)
mkdir -p sources/raw
for id in 216001127 215758617 360051554394; do
  curl -s -o "sources/raw/netflix-$id.json" \
    "https://partnerhelp.netflixstudios.com/api/v2/help_center/en-us/articles/$id.json"
done
