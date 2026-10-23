"""Textänderungen aus LSP-Antworten anwenden (reine Funktionen, ohne Oberfläche)."""


def offsets(text: str) -> list:
    """Startoffset jeder Zeile (für Zeile/Spalte -> Zeichenposition)."""
    pos, out = 0, [0]
    for line in text.split("\n"):
        pos += len(line) + 1
        out.append(pos)
    return out


def apply_edits(text: str, edits: list) -> str:
    """edits: [(Zeile0, Spalte0, Zeile0, Spalte0, Text)] – von hinten nach vorn anwenden, damit sich Positionen nicht verschieben."""
    starts = offsets(text)

    def pos(line: int, col: int) -> int:
        if line >= len(starts) - 1:
            return len(text)
        return min(starts[line] + col, starts[line + 1] - 1 if line + 1 < len(starts) else len(text))
    spans = sorted(((pos(l0, c0), pos(l1, c1), new) for l0, c0, l1, c1, new in edits), key=lambda e: (e[0], e[1]), reverse=True)
    for a, b, new in spans:
        text = text[:a] + new + text[b:]
    return text


def count_occurrences(edits: list) -> int:
    return len(edits)
