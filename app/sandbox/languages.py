"""Language registry: how to write, compile, and run each supported language.
Templates use {src} (source filename) and {exe} (compiled artifact)."""
from __future__ import annotations
import shutil
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Language:
    key: str
    display: str
    source_filename: str
    run_cmd: List[str]
    compile_cmd: Optional[List[str]] = None
    exe: str = ""
    probe: str = ""              # binary whose presence signals availability

    def is_available(self) -> bool:
        return shutil.which(self.probe) is not None if self.probe else True

    def render(self, tokens: List[str]) -> List[str]:
        return [t.replace("{src}", self.source_filename).replace("{exe}", self.exe) for t in tokens]

    def run_argv(self) -> List[str]:
        return self.render(self.run_cmd)

    def compile_argv(self) -> Optional[List[str]]:
        return self.render(self.compile_cmd) if self.compile_cmd else None


_LANGUAGES = {
    "python": Language(
        key="python", display="Python 3", source_filename="main.py",
        run_cmd=["python3", "-I", "-B", "{src}"], probe="python3",
    ),
    "c": Language(
        key="c", display="C (gcc)", source_filename="main.c", exe="a.out",
        compile_cmd=["gcc", "-O2", "-pipe", "-static", "-o", "{exe}", "{src}", "-lm"],
        run_cmd=["./{exe}"], probe="gcc",
    ),
    "cpp": Language(
        key="cpp", display="C++17 (g++)", source_filename="main.cpp", exe="a.out",
        compile_cmd=["g++", "-O2", "-pipe", "-std=c++17", "-o", "{exe}", "{src}"],
        run_cmd=["./{exe}"], probe="g++",
    ),
    "javascript": Language(
        key="javascript", display="JavaScript (Node)", source_filename="main.js",
        run_cmd=["node", "{src}"], probe="node",
    ),
    "java": Language(
        key="java", display="Java", source_filename="Main.java",
        compile_cmd=["javac", "{src}"],
        run_cmd=["java", "-XX:-UsePerfData", "-cp", ".", "Main"], probe="javac",
    ),
}


def get_language(key: str) -> Language:
    key = (key or "python").lower()
    if key not in _LANGUAGES:
        raise KeyError(f"unsupported language: {key}")
    return _LANGUAGES[key]


def available_languages() -> List[dict]:
    return [
        {"key": l.key, "display": l.display, "available": l.is_available()}
        for l in _LANGUAGES.values()
    ]
