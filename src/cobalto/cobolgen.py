"""Writer for generated fixed-format COBOL that keeps a line map to the source."""

AREA_A = " " * 7
AREA_B = " " * 11


class CobolWriter:
    """Collects fixed-format COBOL lines and remembers which line of the
    test file each one came from (to map compile errors back to it)."""

    def __init__(self, limit=72):
        self.lines = []
        self.origin = []
        self.limit = limit

    def a(self, text, origin=None):
        self._emit(AREA_A + text, origin)

    def b(self, text, origin=None, indent=0):
        self._emit(AREA_B + " " * indent + text, origin)

    def raw(self, text, origin=None):
        self._emit(text.rstrip("\n"), origin)

    def comment(self, text):
        self._emit("      * " + text[:64], None)

    def _emit(self, line, origin):
        if len(line) > self.limit:
            raise ValueError(f"generated line exceeds {self.limit} columns: {line!r}")
        self.lines.append(line)
        self.origin.append(origin)

    def move_literal(self, text, target, origin=None, indent=0):
        """MOVE of a long literal to a field, split with reference
        modification so that no line goes past column 72."""
        text = text.replace('"', "'")
        if not text:
            self.b(f'MOVE SPACES TO {target}', origin, indent)
            return
        self.b(f'MOVE SPACES TO {target}', origin, indent)
        # 11 of margin + MOVE "..." TO target(pp:nn) has to fit in the width
        pos, chunk = 1, max(10, min(30, self.limit - 29 - len(target) - indent))
        for i in range(0, len(text), chunk):
            part = text[i:i + chunk]
            self.b(f'MOVE "{part}" TO {target}({pos}:{len(part)})', origin, indent)
            pos += len(part)

    def text(self):
        return "\n".join(self.lines) + "\n"
