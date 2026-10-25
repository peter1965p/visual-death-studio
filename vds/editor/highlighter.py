"""Syntax-Highlighting über Pygments (deckt praktisch alle Sprachen ab).
Der ganze Text wird entprellt neu gelext, damit Mehrzeiler (Kommentare, Strings) stimmen."""
from pygments.lexers import TextLexer, get_lexer_for_filename, get_lexer_by_name
from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token
from pygments.util import ClassNotFound
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from ..theme import TOKENS

CONTROL = {"if", "else", "elif", "for", "while", "return", "break", "continue", "try", "except", "finally", "raise",
           "switch", "case", "default", "do", "match", "yield", "await", "goto", "throw", "catch", "in", "is"}


def _fmt(color, italic=False):
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    f.setFontItalic(italic)
    return f


FORMATS = {k: _fmt(v, k == "comment") for k, v in TOKENS.items()}


def classify(ttype, value):
    if ttype in Keyword.Type or ttype in Name.Class or ttype in Name.Namespace:
        return "type"
    if ttype in Keyword:
        return "control" if value in CONTROL else "keyword"
    if ttype in Name.Function or ttype in Name.Decorator:
        return "function"
    if ttype in Name.Builtin:
        return "type"
    if ttype in Comment.Preproc or ttype in Comment.PreprocFile:
        return "preproc"
    if ttype in Comment:
        return "comment"
    if ttype in String:
        return "string"
    if ttype in Number:
        return "number"
    if ttype in Name.Variable or ttype in Name.Attribute:
        return "variable"
    if ttype in Operator:
        return "operator"
    return None


class PygmentsHighlighter(QSyntaxHighlighter):
    def __init__(self, document, filename: str = ""):
        super().__init__(document)
        self._cache: dict[int, list] = {}
        self.set_filename(filename)
        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self.relex)
        self._busy = False
        document.contentsChanged.connect(self._changed)

    def _changed(self):
        """Nur echte Textänderungen lösen ein neues Einfärben aus – rehighlight() selbst meldet ebenfalls
        contentsChanged und würde sich sonst endlos (alle 120 ms) selbst anstoßen."""
        if not self._busy:
            self._timer.start()

    def set_filename(self, filename: str):
        if not filename:
            self.lexer = TextLexer()
            return
        try:
            self.lexer = get_lexer_for_filename(filename, stripnl=False, ensurenl=False) #if filename else TextLexer()
            return
        except ClassNotFound:
            pass
        
        # 2. Manuelle Zuordnung für Dateien, die Pygments manchmal verpasst
        # (z.B. wenn die Endung mehrdeutig ist oder Pygments zu streng ist)
        ext = filename.lower().split('.')[-1] if '.' in filename else ''
        
        # Laravel / Web spezifische Erweiterungen
        manual_map = {
            'blade.php': 'php',
            'env': 'text',       # .env Dateien sind oft nur Text
            'yml': 'yaml',
            'yaml': 'yaml',
            'json': 'json',
            'css': 'css',
            'scss': 'scss',
            'less': 'less',
            'js': 'javascript',
            'jsx': 'jsx',
            'ts': 'typescript',
            'tsx': 'tsx',
            'vue': 'vue',
            'html': 'html',
            'xml': 'xml',
            'sql': 'sql',
            'sh': 'bash',
            'bat': 'batch',
            'md': 'markdown',
            'txt': 'text',
            'lock': 'text',      # composer.lock, package-lock.json
            'gitignore': 'text',
        }
        if ext in manual_map:
            try:
                self.lexer = get_lexer_for_name(manual_map[ext], stripnl=False, ensurenl=False)
            except ClassNotFound:
                pass
                self.lexer = TextLexer()
        else:
            self.lexer = TextLexer()
        self._cache = {}

    def relex(self):
        text = self.document().toPlainText()
        cache: dict[int, list] = {}
        line, col = 0, 0
        for _, ttype, value in self.lexer.get_tokens_unprocessed(text):
            kind = classify(ttype, value)
            for i, part in enumerate(value.split("\n")):
                if i:
                    line, col = line + 1, 0
                if kind and part:
                    cache.setdefault(line, []).append((col, len(part), FORMATS[kind]))
                col += len(part)
        self._cache = cache
        self._busy = True
        try:
            self.rehighlight()
        finally:
            self._busy = False

    def highlightBlock(self, text):
        for start, length, fmt in self._cache.get(self.currentBlock().blockNumber(), ()):
            self.setFormat(start, length, fmt)
