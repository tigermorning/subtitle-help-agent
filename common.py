# -*- coding: utf-8 -*-
"""여러 모듈이 함께 쓰는 것."""
from concurrent.futures import ThreadPoolExecutor


def pmap(fn, items, workers=8):
    """여러 건을 동시에 호출한다. 결과 순서는 입력 순서와 같다."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))
