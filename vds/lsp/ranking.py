"""Intelligente Sortierung von Vorschlägen: Fuzzy-Treffer, lokaler Kontext, zuletzt Benutzte, Privates/Veraltetes nach hinten.
Ziel: oben steht, was man an dieser Stelle am wahrscheinlichsten meint – nicht, was alphabetisch zuerst kommt."""
import re

# LSP CompletionItemKind
KIND_NAME = {1: "text", 2: "method", 3: "function", 4: "constructor", 5: "field", 6: "variable", 7: "class", 8: "interface", 9: "module",
             10: "property", 11: "unit", 12: "value", 13: "enum", 14: "keyword", 15: "snippet", 16: "color", 17: "file", 18: "reference",
             19: "folder", 20: "enummember", 21: "constant", 22: "struct", 23: "event", 24: "operator", 25: "typeparam"}
# Grundgewicht je Art: Variablen/Funktionen/Felder sind meist gemeint, Schlüsselwörter/Snippets seltener
KIND_WEIGHT = {"variable": 90, "field": 90, "property": 85, "function": 80, "method": 80, "constant": 75, "enummember": 70, "class": 60,
               "constructor": 60, "struct": 55, "enum": 50, "module": 45, "interface": 40, "keyword": 10, "snippet": 5, "text": 0}


def _words(label: str) -> list:
    """Wortanfänge: snake_case, camelCase, PascalCase -> ['get', 'the', 'name']"""
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", label.replace("_", " "))
    return [p.lower() for p in parts if p]


def match_score(label: str, query: str):
    """Rückgabe: (Punkte, Positionen der getroffenen Zeichen) oder None, wenn kein Treffer."""
    if not query:
        return 0, []
    lo, q = label.lower(), query.lower()
    if label.startswith(query):
        return 1000, list(range(len(query)))
    if lo.startswith(q):
        return 900, list(range(len(query)))
    idx = lo.find(q)
    if idx > 0 and (label[idx - 1] in "_." or (label[idx].isupper() and label[idx - 1].islower())):
        return 700, list(range(idx, idx + len(q)))                 # Treffer am Wortanfang mitten im Namen
    # Initialen: "gtn" -> get_the_name / getTheName
    starts = [m.start() for m in re.finditer(r"(?<![A-Za-z0-9])[A-Za-z0-9]|(?<=[a-z0-9])[A-Z]|(?<=_)[A-Za-z0-9]", label)]
    pos, qi = [], 0
    for s in starts:
        if qi < len(q) and lo[s] == q[qi]:
            pos.append(s); qi += 1
    if qi == len(q):
        return 600, pos
    if idx >= 0:
        return 450, list(range(idx, idx + len(q)))
    pos, qi = [], 0                                                  # lose Teilfolge
    for i, ch in enumerate(lo):
        if qi < len(q) and ch == q[qi]:
            pos.append(i); qi += 1
    if qi == len(q):
        span = pos[-1] - pos[0] + 1
        return max(120, 320 - 4 * (span - len(q))), pos
    return None


def rank(items: list, query: str, local_words: set | None = None, mru: dict | None = None) -> list:
    """items: Dicts mit label, kind (int|None), sortText, deprecated, detail. Liefert sortierte Liste mit Feldern _score/_pos."""
    local_words, mru = local_words or set(), mru or {}
    out = []
    for it in items:
        label = it.get("name") or it.get("filterText") or it["label"]       # reiner Name ohne Parameterliste
        m = match_score(label, query)
        if m is None:
            continue
        score, pos = m
        kind = KIND_NAME.get(it.get("kind") or 1, "text")
        score += KIND_WEIGHT.get(kind, 20)
        if label in local_words:
            score += 160                                              # kommt in dieser Datei vor -> wahrscheinlich gemeint
        score += min(300, 60 * mru.get(label, 0))             # zuletzt/häufig gewählt
        if label.startswith("_") and not query.startswith("_"):
            score -= 220                                              # Privates nur auf Wunsch
        if it.get("deprecated"):
            score -= 250
        score -= min(40, len(label) // 2)                       # kürzere zuerst bei sonst gleichem Rang
        out.append({**it, "name": label, "_score": score, "_pos": pos if label == it["label"] else pos[:len(query)]})
    out.sort(key=lambda x: (-x["_score"], x.get("sortText") or x["label"], x["label"]))
    return out
