"""Winnowing fingerprints (Schleimer, Wilkerson & Aiken, 2003) over token
k-grams. Selecting the minimum hash in each sliding window guarantees that any
shared run of tokens of length >= w + k - 1 produces at least one shared
fingerprint, giving robust, position-independent copy detection."""
from __future__ import annotations
from typing import Dict, List, Set, Tuple


def _hash_kgram(gram: Tuple[str, ...]) -> int:
    # FNV-1a over the joined k-gram: cheap, well-distributed, deterministic.
    h = 0xcbf29ce484222325
    for ch in "\x1f".join(gram).encode("utf-8"):
        h ^= ch
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def kgram_hashes(tokens: List[str], k: int) -> List[int]:
    if len(tokens) < k:
        return [_hash_kgram(tuple(tokens))] if tokens else []
    return [_hash_kgram(tuple(tokens[i:i + k])) for i in range(len(tokens) - k + 1)]


def fingerprints(tokens: List[str], k: int = 5, w: int = 4) -> Set[int]:
    """Return the set of winnowing fingerprints for a token stream."""
    hashes = kgram_hashes(tokens, k)
    if len(hashes) <= w:
        return set(hashes)
    selected: Set[int] = set()
    min_idx = -1
    for i in range(len(hashes) - w + 1):
        window = hashes[i:i + w]
        # rightmost minimum (canonical winnowing tie-break)
        m = min(range(w), key=lambda j: (window[j], j))
        abs_idx = i + m
        if abs_idx != min_idx:
            selected.add(hashes[abs_idx])
            min_idx = abs_idx
    return selected


def jaccard(a: Set[int], b: Set[int]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def overlap(a: Set[int], b: Set[int]) -> float:
    """Overlap coefficient: fraction of the smaller fingerprint set that is
    shared. More sensitive than Jaccard when one file is copied into a larger
    one."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def similarity(a: Set[int], b: Set[int]) -> Dict[str, float]:
    return {"jaccard": jaccard(a, b), "overlap": overlap(a, b)}
