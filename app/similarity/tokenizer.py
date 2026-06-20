"""Language-aware tokenization with identifier/literal normalization.

The key idea for code-similarity is to collapse identifiers -> "ID", numbers ->
"NUM", strings -> "STR" while keeping keywords and operators verbatim. This makes
the token stream invariant to variable renaming and reformatting -- the two
cheapest ways students disguise copied code -- so downstream fingerprinting
compares *structure*, not surface text."""
from __future__ import annotations
import io
import keyword
import re
import tokenize
from typing import List

# Keyword sets for the regex tokenizer (non-Python languages).
_KEYWORDS = {
    "c": {
        "auto", "break", "case", "char", "const", "continue", "default", "do",
        "double", "else", "enum", "extern", "float", "for", "goto", "if", "int",
        "long", "register", "return", "short", "signed", "sizeof", "static",
        "struct", "switch", "typedef", "union", "unsigned", "void", "volatile",
        "while", "include", "define",
    },
    "cpp": {
        "alignas", "alignof", "auto", "bool", "break", "case", "catch", "char",
        "class", "const", "constexpr", "continue", "decltype", "default", "delete",
        "do", "double", "else", "enum", "explicit", "export", "extern", "false",
        "float", "for", "friend", "goto", "if", "inline", "int", "long", "mutable",
        "namespace", "new", "nullptr", "operator", "private", "protected", "public",
        "return", "short", "signed", "sizeof", "static", "struct", "switch",
        "template", "this", "throw", "true", "try", "typedef", "typename", "union",
        "unsigned", "using", "virtual", "void", "volatile", "while", "include",
        "std", "vector", "string", "cout", "cin", "endl",
    },
    "javascript": {
        "break", "case", "catch", "class", "const", "continue", "debugger",
        "default", "delete", "do", "else", "export", "extends", "finally", "for",
        "function", "if", "import", "in", "instanceof", "let", "new", "return",
        "super", "switch", "this", "throw", "try", "typeof", "var", "void", "while",
        "with", "yield", "async", "await", "of", "true", "false", "null", "undefined",
        "console", "log",
    },
    "java": {
        "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
        "class", "const", "continue", "default", "do", "double", "else", "enum",
        "extends", "final", "finally", "float", "for", "goto", "if", "implements",
        "import", "instanceof", "int", "interface", "long", "native", "new",
        "package", "private", "protected", "public", "return", "short", "static",
        "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
        "transient", "try", "void", "volatile", "while", "true", "false", "null",
        "String", "System", "out", "println",
    },
}

# Order matters: strings/chars/comments before identifiers and operators.
_GENERIC_SCANNER = re.compile(
    r"""
    (?P<lcomment>//[^\n]*)
  | (?P<bcomment>/\*.*?\*/)
  | (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)
  | (?P<number>\b\d+\.?\d*(?:[eE][+-]?\d+)?\b|\b0[xX][0-9a-fA-F]+\b)
  | (?P<ident>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<op>[-+*/%=<>!&|^~?:.,;(){}\[\]]+)
  | (?P<ws>\s+)
    """,
    re.VERBOSE | re.DOTALL,
)


def _tokenize_python(source: str) -> List[str]:
    out: List[str] = []
    try:
        toks = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in toks:
            tt, ts = tok.type, tok.string
            if tt in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                      tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING,
                      tokenize.ENDMARKER):
                continue
            if tt == tokenize.NAME:
                out.append(ts if keyword.iskeyword(ts) else "ID")
            elif tt == tokenize.NUMBER:
                out.append("NUM")
            elif tt in (tokenize.STRING, getattr(tokenize, "FSTRING_START", -1),
                        getattr(tokenize, "FSTRING_MIDDLE", -1),
                        getattr(tokenize, "FSTRING_END", -1)):
                out.append("STR")
            elif tt == tokenize.OP:
                out.append(ts)
            # ignore everything else
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # fall back to the generic scanner on malformed Python
        return _tokenize_generic(source, "python")
    return out


def _tokenize_generic(source: str, language: str) -> List[str]:
    kws = _KEYWORDS.get(language, set())
    out: List[str] = []
    for m in _GENERIC_SCANNER.finditer(source):
        kind = m.lastgroup
        val = m.group()
        if kind in ("lcomment", "bcomment", "ws"):
            continue
        if kind == "string":
            out.append("STR")
        elif kind == "number":
            out.append("NUM")
        elif kind == "ident":
            out.append(val if val in kws else "ID")
        elif kind == "op":
            out.append(val)
    return out


def tokenize_code(source: str, language: str) -> List[str]:
    language = (language or "python").lower()
    if language == "python":
        return _tokenize_python(source)
    return _tokenize_generic(source, language)
