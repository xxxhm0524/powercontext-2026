"""Tokenisation and bilingual query expansion.

The corpus mixes Chinese prose with English identifiers (status, min_total,
list_orders).  A tiny domain synonym table plus character n-grams gives good
recall without pulling in a heavyweight Chinese segmenter.
"""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

STOP_TERMS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "with",
    "on",
    "is",
    "are",
    "be",
    "this",
    "that",
    "it",
    "as",
    "by",
    "from",
    "def",
    "return",
    "self",
    "none",
    "true",
    "false",
    "的",
    "了",
    "和",
    "与",
    "在",
    "为",
    "按",
    "及",
    "或",
    "是",
    "有",
    "请",
    "需要",
    "一个",
    "本次",
    "任务",
    "相关",
    "哪些",
    "如何",
    "什么",
    "进行",
    "使用",
    "通过",
    "支持",
    "实现",
    "增加",
    "提供",
    "必须",
    "应该",
    "可以",
}

SYNONYMS: dict[str, tuple[str, ...]] = {
    "筛选": ("filter", "filters", "filtering"),
    "过滤": ("filter", "filters"),
    "状态": ("status", "state"),
    "最低": ("min", "minimum", "min_total"),
    "金额": ("total", "amount", "min_total"),
    "订单": ("order", "orders"),
    "列表": ("list", "listing", "list_orders"),
    "分页": ("pagination", "page", "limit", "offset"),
    "排序": ("sort", "sorted", "created_at"),
    "测试": ("test", "tests", "pytest"),
    "规格": ("spec", "specs", "specification", "requirement"),
    "回归": ("regression", "compatibility"),
    "校验": ("validate", "validation", "invalid"),
    "参数": ("parameter", "argument", "param"),
    "接口": ("interface", "api"),
}

# Reverse direction is useful when the task is written mostly in English.
SYNONYMS_REVERSE: dict[str, list[str]] = {}
for _cn, _en_values in SYNONYMS.items():
    for _en in _en_values:
        SYNONYMS_REVERSE.setdefault(_en, []).append(_cn)


def _english_tokens(text: str) -> list[str]:
    out: list[str] = []
    for match in _WORD.finditer(text):
        word = match.group(0).lower()
        if word in STOP_TERMS:
            continue
        out.append(word)
        if "_" in word:
            out.extend(part for part in word.split("_") if part and part not in STOP_TERMS)
    return out


def _cjk_ngrams(text: str) -> list[str]:
    out: list[str] = []
    for sequence in _CJK.findall(text):
        if sequence in STOP_TERMS:
            continue
        # Keep short domain words whole, and every 2/3-gram for longer runs.
        if len(sequence) <= 4:
            out.append(sequence)
        for size in (2, 3):
            if len(sequence) < size:
                continue
            for index in range(len(sequence) - size + 1):
                gram = sequence[index : index + size]
                if gram in STOP_TERMS:
                    continue
                out.append(gram)
    return out


def raw_tokens(text: str) -> list[str]:
    """Tokenise without synonym expansion."""

    return _english_tokens(text) + _cjk_ngrams(text)


def expand_terms(text: str) -> list[str]:
    """Tokenise and add domain synonyms, preserving first-seen order."""

    ordered: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        term = term.strip().lower()
        if not term or term in seen or term in STOP_TERMS:
            return
        seen.add(term)
        ordered.append(term)

    for token in raw_tokens(text):
        add(token)
        for synonym in list(SYNONYMS.get(token, ())) + list(SYNONYMS_REVERSE.get(token, ())):
            add(synonym)
    return ordered


def query_terms(text: str) -> list[str]:
    """Terms used to query the seekdb inverted index.

    Keep the list bounded: long task descriptions otherwise drown the ranking
    in low-information bigrams.
    """

    terms = expand_terms(text)
    # Prefer English identifiers and longer Chinese grams when truncating.
    def weight(term: str) -> tuple[int, int]:
        is_ascii = all(ord(char) < 128 for char in term)
        return (0 if is_ascii else 1, -len(term))

    return sorted(terms, key=weight)[:120]
