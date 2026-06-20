"""Structural similarity for Python via AST node-type sequences.

Flattening the AST to a pre-order stream of node *types* (e.g. FunctionDef, For,
BinOp, Add) discards identifiers and literal values entirely, so it captures the
control/expression skeleton of a program. Fingerprinting that stream catches
structural copies that survive aggressive renaming and reformatting."""
from __future__ import annotations
import ast
from typing import List, Optional, Set

from . import winnowing


def node_type_sequence(source: str) -> Optional[List[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    seq: List[str] = []
    for node in ast.walk(tree):
        name = type(node).__name__
        if name in ("Module", "Load", "Store", "Del"):
            continue
        # include operator subclasses (Add/Sub/...) which carry structure
        seq.append(name)
    return seq


def fingerprints(source: str, k: int = 6, w: int = 4) -> Optional[Set[int]]:
    seq = node_type_sequence(source)
    if seq is None:
        return None
    return winnowing.fingerprints(seq, k=k, w=w)


def similarity(src_a: str, src_b: str) -> Optional[float]:
    fa = fingerprints(src_a)
    fb = fingerprints(src_b)
    if fa is None or fb is None:
        return None
    return winnowing.overlap(fa, fb)
