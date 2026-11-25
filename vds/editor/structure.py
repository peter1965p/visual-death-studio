"""Logik hinter Faltung, Klammern, wandernden Zeilenmarken und Zurück/Vor. Ohne Widgets, damit sie sich direkt prüfen lässt."""
from pathlib import Path

OPENING, CLOSING = "([{", ")]}"
PAIRS = {"(": ")", "[": "]", "{": "}", ")": "(", "]": "[", "}": "{"}
BRACKET_REACH = 20000            # so viele Zeichen sucht die Klammer-Hervorhebung, damit Tippen in großen Dateien flüssig bleibt
NAV_JUMP_LINES = 10              # ein kleinerer Sprung gilt als Weiterarbeiten an derselben Stelle


def indent_width(text: str, tab: int) -> int:
    n = 0
    for ch in text:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += tab - n % tab
        else:
            break
    return n


def fold_end(lines, start: int, tab: int) -> int | None:
    """Letzte Zeile des Blocks, der in Zeile `start` beginnt (nach Einrückung), oder None, wenn dort nichts zu falten ist.
    `lines` ist ein Aufruf Zeilennummer → Text bzw. None hinter dem Dateiende. Leerzeilen am Blockende bleiben sichtbar."""
    head = lines(start)
    if head is None or not head.strip():
        return None
    base, last, n = indent_width(head, tab), None, start + 1
    while (text := lines(n)) is not None:
        if text.strip():
            if indent_width(text, tab) <= base:
                break
            last = n
        n += 1
    return last


def match_bracket(char_at, length: int, pos: int) -> tuple[int, int] | None:
    """Das Klammerpaar am Cursor: erst das Zeichen rechts vom Cursor, dann das links davon. Wie in vielen Editoren zählt jede Klammer,
    auch in Texten und Kommentaren; das Paar stimmt deshalb dort nicht immer."""
    for at in (pos, pos - 1):
        if not 0 <= at < length:
            continue
        ch = char_at(at)
        if ch in PAIRS:
            step = 1 if ch in OPENING else -1
            other, depth, i = PAIRS[ch], 0, at
            for _ in range(BRACKET_REACH):
                i += step
                if not 0 <= i < length:
                    return None
                c = char_at(i)
                if c == ch:
                    depth += 1
                elif c == other:
                    if depth == 0:
                        return (at, i)
                    depth -= 1
            return None
    return None


def shift_lines(marks: set[int], line: int, delta: int) -> set[int]:
    """Zeilenmarken (1-basiert) nach einer Änderung bei Zeile `line`, die `delta` Zeilen dazugebracht oder entfernt hat.
    Marken in gelöschten Zeilen rücken auf die Zeile der Änderung, statt zu verschwinden oder auf fremdem Code zu landen."""
    if delta >= 0:
        return {m + delta if m > line else m for m in marks}
    return {m + delta if m > line - delta else (line if m > line else m) for m in marks}


class NavHistory:
    """Zurück/Vor über die Stellen, an denen gearbeitet wurde. Kleine Bewegungen aktualisieren die aktuelle Stelle, statt neue anzulegen."""

    def __init__(self, limit: int = 100):
        self.entries: list[tuple[Path, int]] = []
        self.index = -1
        self.limit = limit

    def note(self, path: Path, line: int):
        if self.index >= 0:
            cur_path, cur_line = self.entries[self.index]
            if cur_path == path and abs(cur_line - line) < NAV_JUMP_LINES:
                self.entries[self.index] = (path, line)
                return
        del self.entries[self.index + 1:]
        self.entries.append((path, line))
        if len(self.entries) > self.limit:
            del self.entries[0]
        self.index = len(self.entries) - 1

    def back(self) -> tuple[Path, int] | None:
        if self.index <= 0:
            return None
        self.index -= 1
        return self.entries[self.index]

    def forward(self) -> tuple[Path, int] | None:
        if self.index >= len(self.entries) - 1:
            return None
        self.index += 1
        return self.entries[self.index]
