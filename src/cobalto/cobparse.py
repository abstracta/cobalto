#!/usr/bin/env python3
"""cobparse - minimal COBOL parser for Cobalto (CBLT). Stdlib only, written from scratch.

It is not a full parser of the language: it understands just enough for
the CLI to rewrite a program in in-program mode:

  - fixed format (columns 1-6 sequence, 7 indicator, 8-72 code) and
    free format; comments, debug lines and literal continuations with
    "-" in column 7
  - COPY name [OF/IN lib] [REPLACING ...] resolved by looking for the
    copybook in a list of directories; the expanded text remembers
    which file and line each line came from
  - divisions and sections, PROGRAM-ID, END PROGRAM, the USING of the
    PROCEDURE DIVISION, SELECT (name, FILE STATUS), FD and its
    records, WORKING-STORAGE/LINKAGE items with level and name
  - paragraphs and sections of the PROCEDURE DIVISION with their token
    and line ranges
  - statements with their exact extent, including multi-line ones with
    conditional phrases (AT END, NOT AT END, INVALID KEY, ON
    EXCEPTION, ON SIZE ERROR, ON OVERFLOW) and END-xxx terminators,
    IF/ELSE, EVALUATE/WHEN, inline PERFORM, SEARCH and EXEC ... END-EXEC

What it does not do: validate syntax, resolve types, REPLACE, nested
programs, free format with "&" continuation. If something is not
understood, it advances token by token without breaking.
"""
import os
import re

COPY_EXTS = ["", ".cpy", ".CPY", ".cob", ".COB", ".cbl", ".CBL", ".copy", ".COPY",
             ".lib", ".LIB", ".inc", ".INC"]

VERBS = {
    "ACCEPT", "ADD", "ALLOCATE", "ALTER", "CALL", "CANCEL", "CLOSE", "COMMIT",
    "COMPUTE", "CONTINUE", "DELETE", "DISABLE", "DISPLAY", "DIVIDE", "ENABLE",
    "ENTRY", "EVALUATE", "EXEC", "EXIT", "FREE", "GENERATE", "GO", "GOBACK", "IF",
    "INITIALIZE", "INITIATE", "INSPECT", "INVOKE", "JSON", "MERGE", "MOVE",
    "MULTIPLY", "OPEN", "PERFORM", "PURGE", "RAISE", "READ", "READY", "RECEIVE",
    "RELEASE", "RESET", "RESUME", "RETURN", "REWRITE", "ROLLBACK", "SEARCH",
    "SEND", "SET", "SORT", "START", "STOP", "STRING", "SUBTRACT", "SUPPRESS",
    "TERMINATE", "UNLOCK", "UNSTRING", "VALIDATE", "WRITE", "XML",
}

TERMINATORS = {
    "END-ACCEPT", "END-ADD", "END-CALL", "END-COMPUTE", "END-DELETE",
    "END-DISPLAY", "END-DIVIDE", "END-EVALUATE", "END-EXEC", "END-IF",
    "END-INVOKE", "END-JSON", "END-MULTIPLY", "END-PERFORM", "END-READ",
    "END-RECEIVE", "END-RETURN", "END-REWRITE", "END-SEARCH", "END-START",
    "END-STRING", "END-SUBTRACT", "END-UNSTRING", "END-WRITE", "END-XML",
}

ARITH = {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"}
VERB_PHRASES = {
    "READ": {"AT END", "INVALID KEY"},
    "RETURN": {"AT END"},
    "WRITE": {"INVALID KEY", "AT EOP"},
    "REWRITE": {"INVALID KEY"},
    "DELETE": {"INVALID KEY"},
    "START": {"INVALID KEY"},
    "CALL": {"ON EXCEPTION", "ON OVERFLOW"},
    "STRING": {"ON OVERFLOW"},
    "UNSTRING": {"ON OVERFLOW"},
    "SEARCH": {"AT END"},
    # ACCEPT and DISPLAY have ON EXCEPTION in COBOL 2002, but in legacy
    # code "CALL ... ON EXCEPTION DISPLAY x NOT ON EXCEPTION ..." the NOT
    # belongs to the CALL; they are treated as simple verbs on purpose.
}
for _v in ARITH:
    VERB_PHRASES[_v] = {"ON SIZE ERROR"}

DATA_SECTIONS = ("FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE", "REPORT",
                 "SCREEN", "COMMUNICATION")

WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_$#@-]*")
NUM_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")


class ParseError(Exception):
    pass


class Line:
    """A physical line of the expanded source file."""
    __slots__ = ("text", "no", "origin", "kind", "code", "code_col")

    def __init__(self, text, no, origin, kind, code, code_col):
        self.text, self.no, self.origin = text, no, origin
        self.kind, self.code, self.code_col = kind, code, code_col   # kind: code cont comment blank directive

    def __repr__(self):
        return f"Line({self.no},{self.kind},{self.text!r})"


class Token:
    __slots__ = ("kind", "text", "up", "line", "col", "end_line", "end_col")

    def __init__(self, kind, text, line, col):
        self.kind, self.text, self.up = kind, text, text.upper()   # kind: word num lit sep pic
        self.line, self.col, self.end_line, self.end_col = line, col, line, col + len(text) - 1

    def __repr__(self):
        return f"{self.kind}:{self.text}@{self.line}"


class Stmt:
    """A PROCEDURE DIVISION statement: tokens [start, end)."""
    __slots__ = ("verb", "start", "end", "terminated", "phrases", "main_end", "depth", "line", "end_line")

    def __init__(self, verb, start):
        self.verb, self.start, self.end = verb, start, start
        self.terminated, self.phrases, self.main_end, self.depth = False, [], start, 0
        self.line = self.end_line = 0

    @property
    def has_phrase(self):
        return bool(self.phrases)

    def needs_terminator(self):
        """True if the statement depends on the period to be closed."""
        if self.terminated:
            return False
        if self.verb in ("IF", "EVALUATE", "SEARCH"):
            return True
        if self.verb == "PERFORM":
            return self.depth == -1          # -1 marks an inline PERFORM
        return self.has_phrase

    def terminator(self):
        return "END-" + self.verb


class Paragraph:
    __slots__ = ("name", "section", "is_section", "header", "body_start", "body_end", "line", "end_line")

    def __init__(self, name, section, is_section, header):
        self.name, self.section, self.is_section, self.header = name, section, is_section, header
        self.body_start = self.body_end = header
        self.line = self.end_line = 0


class DataItem:
    __slots__ = ("level", "name", "line", "section", "fd", "tok")

    def __init__(self, level, name, line, section, fd, tok):
        self.level, self.name, self.line, self.section, self.fd, self.tok = level, name, line, section, fd, tok


# ---------------------------------------------------------------- format and COPY
def detect_format(text_lines):
    for raw in text_lines[:400]:
        s = raw.strip()
        if re.match(r"^>>\s*SOURCE\s+(FORMAT\s+)?(IS\s+)?FREE\b", s, re.I):
            return "free"
        if re.match(r"^>>\s*SOURCE\s+(FORMAT\s+)?(IS\s+)?FIXED\b", s, re.I):
            return "fixed"
        if re.search(r"\$SET\s+SOURCEFORMAT\s*\(?\s*\"?FREE", s, re.I):
            return "free"
    for raw in text_lines:
        m = re.match(r"^(\s*)(IDENTIFICATION|ID|PROGRAM-ID)\b", raw, re.I)
        if m:
            return "free" if len(m.group(1).expandtabs(8)) < 7 else "fixed"
    return "fixed"


def classify(raw, fmt):
    """Return (kind, code, code_col) for a physical line."""
    text = raw.expandtabs(8).rstrip("\n").rstrip()
    if fmt == "fixed":
        if len(text) <= 6 or not text[6:].strip():
            return "blank", "", 8
        ind = text[6]
        code = text[7:72]
        if ind in "*/":
            return "comment", "", 8
        if ind in "Dd":
            return "comment", "", 8
        if ind == "-":
            return "cont", code, 8
        if ind == "$":
            return "directive", "", 8
        if code.lstrip().startswith(">>") or code.lstrip().startswith("$"):
            return "directive", "", 8
        return "code", code, 8
    s = text.lstrip()
    if not s:
        return "blank", "", 1
    if s.startswith("*>") or text[:1] in "*/":
        return "comment", "", 1
    if s.startswith(">>") or s.startswith("$"):
        return "directive", "", 1
    return "code", text, 1


def in_literal(text):
    """Whether text ends inside a literal that is still open."""
    quote = None
    for c in text:
        if quote is None and c in "'\"":
            quote = c
        elif c == quote:
            quote = None
    return quote is not None


# the word COPY whole: COPY-RECORD is a name, not a COPY statement
COPY_WORD = r"COPY(?![A-Za-z0-9-])"


def split_copy_stmt(code):
    """If the code area contains 'COPY' as its first word or
    right after a period, return (before, from_copy)."""
    if re.match(r"^\s*" + COPY_WORD, code, re.I):
        return "", code
    for m in re.finditer(r"\.\s+" + COPY_WORD, code, re.I):
        if not in_literal(code[:m.start()]):
            return code[:m.start() + 1], code[m.start() + 1:]
    return None


def find_copybook(name, dirs):
    name = name.strip("'\"")
    for d in dirs:
        for cand in (name, name.upper(), name.lower()):
            for ext in COPY_EXTS:
                p = os.path.join(d, cand + ext)
                if os.path.isfile(p):
                    return p
    return None


def parse_copy_clause(text):
    """'COPY X OF LIB REPLACING ==A== BY ==B== Y BY Z.' ->
    (name, [(a, b), ...])."""
    body = text.strip()
    if body.endswith("."):
        body = body[:-1]
    m = re.match(r"^COPY\s+('[^']*'|\"[^\"]*\"|[A-Za-z0-9][A-Za-z0-9_$#@.-]*)", body, re.I)
    if not m:
        raise ParseError(f"unrecognized COPY: {text.strip()}")
    name = m.group(1)
    rest = body[m.end():]
    reps = []
    rm = re.search(r"\bREPLACING\b", rest, re.I)
    if rm:
        rest = rest[rm.end():]
        pat = re.compile(r"\s*(==.*?==|'[^']*'|\"[^\"]*\"|\S+)\s+BY\s+(==.*?==|'[^']*'|\"[^\"]*\"|\S+)", re.I | re.S)
        for a, b in pat.findall(rest):
            strip = lambda x: x[2:-2] if x.startswith("==") else x
            reps.append((strip(a).strip(), strip(b).strip()))
    return name, reps


def apply_replacing(lines, reps):
    if not reps:
        return lines
    out = []
    for text in lines:
        for a, b in reps:
            if re.match(r"^[A-Za-z0-9-]+$", a):
                text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(a) + r"(?![A-Za-z0-9-])", b, text, flags=re.I)
            else:
                text = text.replace(a, b)
        out.append(text)
    return out


def load_lines(path, copy_dirs=None, fmt=None, _depth=0, _reps=None):
    """Read a source file, expand COPY and return (format, [Line])."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read().splitlines()
    if _reps:
        raw = apply_replacing(raw, _reps)
    if fmt is None:
        fmt = detect_format(raw)
    dirs = [os.path.dirname(os.path.abspath(path))] + list(copy_dirs or [])
    out = []
    i = 0
    while i < len(raw):
        text = raw[i].expandtabs(8).rstrip("\n").rstrip()
        kind, code, col = classify(text, fmt)
        if kind == "code":
            sp = split_copy_stmt(code)
            if sp:
                before, copy_text = sp
                # join lines up to the period that closes the COPY
                j = i
                full = copy_text
                while not re.search(r"\.\s*$", full.split("*>")[0]) and j + 1 < len(raw):
                    j += 1
                    k2, c2, _ = classify(raw[j], fmt)
                    if k2 == "code":
                        full += " " + c2.strip()
                name, reps = parse_copy_clause(full)
                if before.strip():
                    pre = text[:col - 1] + before.rstrip()
                    out.append(Line(pre, 0, (path, i + 1), "code", before, col))
                cp = find_copybook(name, dirs)
                if not cp:
                    raise ParseError(f"copybook '{name.strip(chr(39) + chr(34))}' not found "
                                     f"(searched in {', '.join(dirs)}); referenced in {path}:{i + 1}")
                if _depth > 20:
                    raise ParseError(f"COPY nested too deeply at {path}:{i + 1}")
                _, sub = load_lines(cp, copy_dirs, fmt, _depth + 1, reps)
                out.extend(sub)
                i = j + 1
                continue
        out.append(Line(text, 0, (path, i + 1), kind, code, col))
        i += 1
    if _depth == 0:
        for n, ln in enumerate(out, 1):
            ln.no = n
    return fmt, out


# ---------------------------------------------------------------- tokenizer
def tokenize(lines, fmt):
    tokens = []
    pending = None        # open literal: [quote, text, line, col]
    pic_next = False
    for ln in lines:
        if ln.kind not in ("code", "cont"):
            continue
        s, n = ln.code, len(ln.code)
        base = ln.code_col
        i = 0
        if ln.kind == "cont":
            while i < n and s[i] == " ":
                i += 1
            if pending is not None:
                if i < n and s[i] == pending[0]:
                    i += 1
            elif tokens and i < n:
                # continuation of a word: it is appended to the previous token
                m = WORD_RE.match(s, i)
                if m and tokens[-1].kind in ("word", "num"):
                    tokens[-1].text += m.group(0)
                    tokens[-1].up = tokens[-1].text.upper()
                    tokens[-1].end_line, tokens[-1].end_col = ln.no, base + m.end() - 1
                    i = m.end()
        while i < n:
            if pending is not None:
                q = pending[0]
                j = i
                closed = False
                while j < n:
                    if s[j] == q:
                        if j + 1 < n and s[j + 1] == q:
                            # a doubled quote is part of the literal and stays
                            # doubled: the token is the text as written
                            pending[1] += q + q
                            j += 2
                            continue
                        closed = True
                        break
                    pending[1] += s[j]
                    j += 1
                if closed:
                    t = Token("lit", pending[4] + q + pending[1] + q, pending[2], pending[3])
                    t.end_line, t.end_col = ln.no, base + j
                    tokens.append(t)
                    pending = None
                    i = j + 1
                    continue
                if fmt == "free":
                    t = Token("lit", pending[4] + q + pending[1] + q, pending[2], pending[3])
                    tokens.append(t)
                    pending = None
                i = n
                break
            c = s[i]
            if c == " ":
                i += 1
                continue
            if s.startswith("*>", i):
                break
            if pic_next:
                m = re.match(r"\S+", s[i:])
                pic = m.group(0)
                if pic.upper() == "IS":
                    tokens.append(Token("word", pic, ln.no, base + i))
                    i += 2
                    continue
                drop = pic.endswith(".") and (i + len(pic) >= n or s[i + len(pic)] == " ")
                if drop:
                    pic = pic[:-1]
                tokens.append(Token("pic", pic, ln.no, base + i))
                i += len(pic)
                if drop:
                    tokens.append(Token("sep", ".", ln.no, base + i))
                    i += 1
                pic_next = False
                continue
            if c in "\"'":
                pending = [c, "", ln.no, base + i, ""]
                i += 1
                continue
            if c.upper() in "XNZGHB" and i + 1 < n and s[i + 1] in "\"'" and \
                    (i == 0 or not (s[i - 1].isalnum() or s[i - 1] in "-_")):
                pending = [s[i + 1], "", ln.no, base + i, c]
                i += 2
                continue
            if c == "=" and s.startswith("==", i):
                tokens.append(Token("sep", "==", ln.no, base + i))
                i += 2
                continue
            if c in "+-" and i + 1 < n and (s[i + 1].isdigit() or s[i + 1] == ".") and \
                    (i == 0 or s[i - 1] == " ") and (i + 2 >= n or s[i + 2] != " " or s[i + 1].isdigit()):
                m = re.match(r"[+-](\d+\.?\d*|\.\d+)", s[i:])
                if m and (i + m.end() >= n or not (s[i + m.end()].isalnum() or s[i + m.end()] == "-")):
                    tokens.append(Token("num", m.group(0), ln.no, base + i))
                    i += m.end()
                    continue
            if c == "." and i + 1 < n and s[i + 1].isdigit():
                m = re.match(r"\.\d+", s[i:])
                tokens.append(Token("num", m.group(0), ln.no, base + i))
                i += m.end()
                continue
            if c.isalnum():
                m = WORD_RE.match(s, i)
                word = m.group(0)
                # number with decimals: 12.5 (the period is not a separator if a digit follows)
                if word.isdigit() and i + len(word) + 1 < n and s[i + len(word)] == "." and s[i + len(word) + 1].isdigit():
                    m2 = re.match(r"\d+\.\d+", s[i:])
                    word = m2.group(0)
                kind = "num" if NUM_RE.match(word) else "word"
                t = Token(kind, word, ln.no, base + i)
                tokens.append(t)
                if t.up in ("PIC", "PICTURE"):
                    pic_next = True
                i += len(word)
                continue
            if c == ".":
                tokens.append(Token("sep", ".", ln.no, base + i))
                i += 1
                continue
            if c in ",;":
                i += 1
                continue
            two = s[i:i + 2]
            if two in ("**", ">=", "<="):
                tokens.append(Token("sep", two, ln.no, base + i))
                i += 2
                continue
            tokens.append(Token("sep", c, ln.no, base + i))
            i += 1
    if pending is not None:
        t = Token("lit", pending[4] + pending[0] + pending[1] + pending[0], pending[2], pending[3])
        tokens.append(t)
    return tokens


# ---------------------------------------------------------------- program
class Program:
    def __init__(self, path, copy_dirs=None):
        self.path = path
        self.fmt, self.lines = load_lines(path, copy_dirs)
        self.tokens = tokenize(self.lines, self.fmt)
        self.line_by_no = {ln.no: ln for ln in self.lines}
        self.first_tok_of_line = {}
        for idx, t in enumerate(self.tokens):
            self.first_tok_of_line.setdefault(t.line, idx)
        self.program_ids = []        # [(name, name_token_idx)]
        self.end_programs = []       # [(name, END_token_idx, name_token_idx)]
        self.divisions = {}          # name -> token idx
        self.sections = {}           # (division, name) -> token idx
        self.data_items = []
        self.files = {}              # name -> dict(status, org, records, select_tok, fd_tok)
        self.record_file = {}        # 01 record name -> file
        self.procedure_using = []
        self.procedure_tok = None    # idx of the PROCEDURE token
        self.procedure_body = None   # idx of the first token after the period of the header
        self.procedure_end = None    # idx (exclusive) of the body: END PROGRAM or end
        self.declaratives = None     # (start, end) tokens incl. END DECLARATIVES .
        self.body_begin = None       # idx of the first token of the body (after DECLARATIVES)
        self.nested = False          # there is another PROGRAM-ID after the body
        self.paragraphs = []
        self.statements = []
        self.has_sections = False
        self._analyze()

    # --------------------------------------------------------- utilities
    def up(self, i):
        return self.tokens[i].up if 0 <= i < len(self.tokens) else ""

    def kind(self, i):
        return self.tokens[i].kind if 0 <= i < len(self.tokens) else ""

    def origin_of_line(self, no):
        ln = self.line_by_no.get(no)
        return ln.origin if ln else (self.path, no)

    @property
    def program_id(self):
        return self.program_ids[0][0] if self.program_ids else None

    def paragraph(self, name):
        name = name.upper()
        for p in self.paragraphs:
            if p.name == name:
                return p
        return None

    def file_of_record(self, rec):
        return self.record_file.get(rec.upper())

    # --------------------------------------------------------- analysis
    def _analyze(self):
        T, n = self.tokens, len(self.tokens)
        i = 0
        division = None
        section = None
        cur_fd = None
        at_start = True             # start of statement (after a period)
        while i < n:
            t = T[i]
            u = t.up
            if at_start and self.kind(i) == "word":
                if self.up(i + 1) == "DIVISION" and u in ("IDENTIFICATION", "ID", "ENVIRONMENT", "DATA", "PROCEDURE"):
                    division = "IDENTIFICATION" if u == "ID" else u
                    self.divisions[division] = i
                    section = None
                    if division == "PROCEDURE":
                        self.procedure_tok = i
                        j = i + 2
                        using = []
                        while j < n and self.up(j) != ".":
                            if self.up(j) not in ("USING", "RETURNING", "BY", "REFERENCE", "VALUE", "CONTENT"):
                                using.append(j)
                            j += 1
                        self.procedure_using = using
                        self.procedure_body = j + 1
                        self._analyze_procedure(j + 1)
                        return
                    i += 2
                    at_start = False
                    continue
                if self.up(i + 1) == "SECTION" and division in ("ENVIRONMENT", "DATA"):
                    section = u
                    self.sections[(division, u)] = i
                    i += 2
                    at_start = False
                    continue
                if u == "PROGRAM-ID" and division == "IDENTIFICATION":
                    j = i + 1
                    if self.up(j) == ".":
                        j += 1
                    self.program_ids.append((T[j].text.strip("'\"").upper(), j))
                    i = j + 1
                    at_start = False
                    continue
                if u == "END" and self.up(i + 1) == "PROGRAM":
                    self.end_programs.append((self.up(i + 2).strip("'\""), i, i + 2))
                    i += 3
                    at_start = False
                    continue
                if u == "SELECT" and division == "ENVIRONMENT":
                    j = i + 1
                    if self.up(j) == "OPTIONAL":
                        j += 1
                    fname = self.up(j)
                    info = {"status": None, "org": None, "records": [], "select_tok": i, "fd_tok": None}
                    k = j + 1
                    while k < n and self.up(k) != ".":
                        if self.up(k) == "STATUS" and self.kind(k + 1) == "word":
                            m = k + 1
                            if self.up(m) == "IS":
                                m += 1
                            info["status"] = T[m].text
                        if self.up(k) == "ORGANIZATION":
                            m = k + 1
                            if self.up(m) == "IS":
                                m += 1
                            info["org"] = self.up(m)
                        k += 1
                    self.files[fname] = info
                    i = k
                    at_start = False
                    continue
                if u in ("FD", "SD") and section == "FILE":
                    cur_fd = self.up(i + 1)
                    if cur_fd in self.files:
                        self.files[cur_fd]["fd_tok"] = i
                    elif u == "FD":
                        self.files[cur_fd] = {"status": None, "org": None, "records": [], "select_tok": None, "fd_tok": i}
                    i += 2
                    at_start = False
                    continue
            if at_start and self.kind(i) == "num" and division == "DATA" and t.text.isdigit():
                lvl = int(t.text)
                if 1 <= lvl <= 49 or lvl in (66, 77, 88):
                    name = None
                    if self.kind(i + 1) == "word" and self.up(i + 1) not in (
                            "PIC", "PICTURE", "VALUE", "VALUES", "OCCURS", "REDEFINES", "USAGE",
                            "COMP", "COMP-3", "COMPUTATIONAL", "BINARY", "PACKED-DECIMAL", "SIGN",
                            "JUSTIFIED", "JUST", "BLANK", "EXTERNAL", "GLOBAL", "SYNC", "SYNCHRONIZED"):
                        name = self.up(i + 1)
                    item = DataItem(lvl, name, t.line, section, cur_fd if section == "FILE" else None, i)
                    self.data_items.append(item)
                    if lvl == 1 and section == "FILE" and cur_fd and name:
                        self.files.setdefault(cur_fd, {"status": None, "org": None, "records": [],
                                                       "select_tok": None, "fd_tok": None})
                        self.files[cur_fd]["records"].append(name)
                        self.record_file[name] = cur_fd
                    i += 1
                    at_start = False
                    continue
            at_start = (u == ".")
            i += 1

    def _analyze_procedure(self, start):
        T, n = self.tokens, len(self.tokens)
        # end of the body: END PROGRAM (or a nested IDENTIFICATION DIVISION) or EOF
        end = n
        for j in range(start, n):
            if self.up(j) == "END" and self.up(j + 1) == "PROGRAM":
                end = j
                self.end_programs.append((self.up(j + 2).strip("'\""), j, j + 2))
                break
            if self.up(j) in ("IDENTIFICATION", "ID") and self.up(j + 1) == "DIVISION":
                end = j
                break
        self.procedure_end = end
        self.nested = any(self.up(j) == "PROGRAM-ID" for j in range(end, n))
        i = start
        section = None
        cur = None
        if self.up(i) == "DECLARATIVES" and self.up(i + 1) == ".":
            d0 = i
            j = i + 2
            while j < end and not (self.up(j) == "END" and self.up(j + 1) == "DECLARATIVES"):
                j += 1
            j += 2
            if self.up(j) == ".":
                j += 1
            self.declaratives = (d0, j)
            i = j
        body_begin = i
        self.body_begin = i
        while i < end:
            t = T[i]
            u = t.up
            if t.kind in ("word", "num") and u not in VERBS:
                if self.up(i + 1) == "SECTION" and t.kind == "word":
                    j = i + 2
                    while j < end and self.up(j) != ".":
                        j += 1
                    self._close(cur, i)
                    cur = Paragraph(u, u, True, i)
                    cur.body_start = j + 1
                    cur.line = t.line
                    self.paragraphs.append(cur)
                    self.has_sections = True
                    section = u
                    i = j + 1
                    continue
                if self.up(i + 1) == "." and (i == body_begin or self.up(i - 1) == "."):
                    self._close(cur, i)
                    cur = Paragraph(u, section, False, i)
                    cur.body_start = i + 2
                    cur.line = t.line
                    self.paragraphs.append(cur)
                    i += 2
                    continue
            if u == ".":
                i += 1
                continue
            j = self._parse_stmt(i, 0)
            if j <= i:
                j = i + 1
            i = j
        self._close(cur, end)
        self.statements.sort(key=lambda s: s.start)

    def _close(self, para, idx):
        if para is not None:
            para.body_end = idx
            para.end_line = self.tokens[idx - 1].line if idx - 1 >= 0 else para.line

    # --------------------------------------------------------- statements
    def phrase_at(self, j):
        """(name, length) if a conditional phrase starts at j."""
        u = self.up(j)
        if u == "NOT":
            inner = self.phrase_at(j + 1)
            if inner:
                return ("NOT " + inner[0], 1 + inner[1])
            return None
        if u == "AT":
            if self.up(j + 1) == "END":
                return ("AT END", 2)
            if self.up(j + 1) in ("END-OF-PAGE", "EOP"):
                return ("AT EOP", 2)
            return None
        if u in ("END-OF-PAGE", "EOP"):
            return ("AT EOP", 1)
        if u == "INVALID":
            return ("INVALID KEY", 2 if self.up(j + 1) == "KEY" else 1)
        if u == "ON":
            if self.up(j + 1) == "EXCEPTION":
                return ("ON EXCEPTION", 2)
            if self.up(j + 1) == "OVERFLOW":
                return ("ON OVERFLOW", 2)
            if self.up(j + 1) == "SIZE" and self.up(j + 2) == "ERROR":
                return ("ON SIZE ERROR", 3)
            return None
        if u == "EXCEPTION":
            return ("ON EXCEPTION", 1)
        if u == "OVERFLOW":
            return ("ON OVERFLOW", 1)
        if u == "SIZE" and self.up(j + 1) == "ERROR":
            return ("ON SIZE ERROR", 2)
        return None

    def _record(self, st, end):
        st.end = end
        st.line = self.tokens[st.start].line
        st.end_line = self.tokens[end - 1].line if end - 1 >= st.start else st.line
        self.statements.append(st)
        return end

    def _parse_stmt(self, i, depth):
        v = self.up(i)
        st = Stmt(v, i)
        st.depth = depth
        n = len(self.tokens)
        if v == "IF":
            return self._parse_if(st, depth)
        if v in ("EVALUATE", "SEARCH"):
            return self._parse_evaluate(st, depth)
        if v == "PERFORM":
            return self._parse_perform(st, depth)
        if v == "EXIT" and self.up(i + 1) == "PERFORM":
            # EXIT PERFORM [CYCLE] is one statement, not an EXIT and a PERFORM
            j = i + (3 if self.up(i + 2) == "CYCLE" else 2)
            st.main_end = j
            return self._record(st, j)
        if v == "EXEC":
            j = i + 1
            while j < n and self.up(j) != "END-EXEC":
                j += 1
            if j < n:
                st.terminated = True
                j += 1
            st.main_end = j
            return self._record(st, j)
        j = i + 1
        own = VERB_PHRASES.get(v, set())
        cur = None
        st.main_end = None
        while j < n:
            u = self.up(j)
            if u == ".":
                break
            if u == "END-" + v and u in TERMINATORS:
                st.terminated = True
                self._close_phrase(st, cur, j)
                j += 1
                st.end = j
                st.main_end = st.main_end if st.main_end is not None else j - 1
                return self._record(st, j)
            if u in TERMINATORS or u in ("ELSE", "WHEN"):
                break
            ph = self.phrase_at(j)
            if ph:
                base = ph[0][4:] if ph[0].startswith("NOT ") else ph[0]
                if base in own:
                    self._close_phrase(st, cur, j)
                    if st.main_end is None:
                        st.main_end = j
                    cur = [ph[0], j, j + ph[1], None]
                    st.phrases.append(cur)
                    j += ph[1]
                    continue
                break
            if u in VERBS or (u == "NEXT" and self.up(j + 1) == "SENTENCE"):
                if cur is None:
                    break
                if u == "NEXT":
                    j += 2
                    continue
                j = self._parse_stmt(j, depth + 1)
                continue
            j += 1
        self._close_phrase(st, cur, j)
        if st.main_end is None:
            st.main_end = j
        return self._record(st, j)

    @staticmethod
    def _close_phrase(st, cur, j):
        if cur is not None and cur[3] is None:
            cur[3] = j

    def _parse_if(self, st, depth):
        n = len(self.tokens)
        j = st.start + 1
        seen_else = False
        in_body = False
        while j < n:
            u = self.up(j)
            if u == ".":
                break
            if u == "END-IF":
                st.terminated = True
                j += 1
                return self._record(st, j)
            if u in TERMINATORS or u == "WHEN":
                break
            if u == "ELSE":
                if seen_else:
                    break
                seen_else = True
                j += 1
                continue
            if in_body and self.phrase_at(j):
                break
            if u == "NEXT" and self.up(j + 1) == "SENTENCE":
                in_body = True
                j += 2
                continue
            if u in VERBS:
                in_body = True
                j = self._parse_stmt(j, depth + 1)
                continue
            j += 1
        return self._record(st, j)

    def _parse_evaluate(self, st, depth):
        n = len(self.tokens)
        v = st.verb
        j = st.start + 1
        in_body = False
        while j < n:
            u = self.up(j)
            if u == ".":
                break
            if u == "END-" + v:
                st.terminated = True
                j += 1
                return self._record(st, j)
            if u in TERMINATORS or u == "ELSE":
                break
            if u == "WHEN":
                in_body = False
                j += 1
                continue
            if v == "SEARCH" and u == "AT" and self.up(j + 1) == "END":
                st.phrases.append(["AT END", j, j + 2, None])
                j += 2
                continue
            if in_body and self.phrase_at(j):
                break
            if u == "NEXT" and self.up(j + 1) == "SENTENCE":
                in_body = True
                j += 2
                continue
            if u in VERBS:
                in_body = True
                j = self._parse_stmt(j, depth + 1)
                continue
            j += 1
        return self._record(st, j)

    def _parse_perform(self, st, depth):
        n = len(self.tokens)
        j = st.start + 1
        u1 = self.up(j)
        inline = u1 in VERBS or u1 in ("VARYING", "UNTIL", "WITH", "TEST", "END-PERFORM") or self.up(j + 1) == "TIMES"
        if inline:
            st.depth = -1
            while j < n:
                u = self.up(j)
                if u == ".":
                    break
                if u == "END-PERFORM":
                    st.terminated = True
                    j += 1
                    return self._record(st, j)
                if u in TERMINATORS or u in ("ELSE", "WHEN"):
                    break
                if u == "NEXT" and self.up(j + 1) == "SENTENCE":
                    j += 2
                    continue
                if u in VERBS:
                    j = self._parse_stmt(j, depth + 1)
                    continue
                j += 1
            return self._record(st, j)
        while j < n:
            u = self.up(j)
            if u == "." or u in VERBS or u in TERMINATORS or u in ("ELSE", "WHEN"):
                break
            if self.phrase_at(j):
                break
            j += 1
        return self._record(st, j)

    # --------------------------------------------------------- queries
    def statements_in(self, start, end):
        return [s for s in self.statements if s.start >= start and s.end <= end]

    def call_target(self, st):
        """For a CALL: (text_as_is, is_literal)."""
        t = self.tokens[st.start + 1]
        return t.text, t.kind == "lit"

    def file_sites(self):
        """File statements: [(stmt, file, op, details)]."""
        out = []
        for st in self.statements:
            v = st.verb
            if v in ("READ", "DELETE", "START"):
                f = self.up(st.start + 1)
                if f in self.files:
                    out.append((st, f, v, self._read_details(st) if v == "READ" else {}))
            elif v in ("WRITE", "REWRITE"):
                rec = self.up(st.start + 1)
                f = self.record_file.get(rec)
                if f:
                    out.append((st, f, v, self._write_details(st)))
            elif v in ("OPEN", "CLOSE"):
                out.append((st, None, v, self._open_details(st)))
        return out

    def _read_details(self, st):
        d = {"into": None}
        j = st.start + 2
        while j < st.main_end:
            if self.up(j) == "INTO":
                k = j + 1
                parts = []
                while k < st.main_end and self.up(k) not in ("KEY", "WITH", "NEXT", "PREVIOUS"):
                    parts.append(self.tokens[k].text)
                    k += 1
                d["into"] = " ".join(parts)
                break
            j += 1
        return d

    def _write_details(self, st):
        d = {"record": self.tokens[st.start + 1].text, "from": None}
        j = st.start + 2
        while j < st.main_end:
            if self.up(j) == "FROM":
                k = j + 1
                parts = []
                while k < st.main_end and self.up(k) not in ("BEFORE", "AFTER", "WITH", "LOCK"):
                    parts.append(self.tokens[k].text)
                    k += 1
                d["from"] = " ".join(parts)
                break
            j += 1
        return d

    def _open_details(self, st):
        """OPEN INPUT A OUTPUT B / CLOSE A B -> [(mode, file)]."""
        items, mode = [], None
        skip = {"SHARING", "WITH", "NO", "OTHER", "ALL", "READ", "ONLY", "LOCK", "REWIND",
                "REVERSED", "REEL", "UNIT", "FOR", "REMOVAL"}
        for j in range(st.start + 1, st.end):
            u = self.up(j)
            if u in ("INPUT", "OUTPUT", "I-O", "EXTEND"):
                mode = u
            elif u in skip or self.kind(j) != "word":
                continue
            elif u in self.files:
                items.append((mode, u))
        return {"items": items}

    def clock_sites(self):
        """ACCEPT x FROM DATE/DAY/DAY-OF-WEEK/TIME [YYYYMMDD|YYYYDDD]."""
        out = []
        for st in self.statements:
            if st.verb != "ACCEPT":
                continue
            toks = [self.up(j) for j in range(st.start, st.main_end)]
            if "FROM" in toks:
                k = toks.index("FROM")
                src = toks[k + 1] if k + 1 < len(toks) else ""
                if src in ("DATE", "DAY", "DAY-OF-WEEK", "TIME"):
                    kind = src
                    if k + 2 < len(toks) and toks[k + 2] in ("YYYYMMDD", "YYYYDDD"):
                        kind = src + " " + toks[k + 2]
                    target = " ".join(self.tokens[j].text for j in range(st.start + 1, st.start + k))
                    out.append((st, kind, target))
        return out

    def sql_sites(self):
        out = []
        for st in self.statements:
            if st.verb == "EXEC" and self.up(st.start + 1) == "SQL":
                text = " ".join(self.tokens[j].text for j in range(st.start + 2, st.end - (1 if st.terminated else 0)))
                out.append((st, text))
        return out


SITE_VERBS = ("CALL", "READ", "WRITE", "REWRITE", "DELETE", "START", "OPEN", "CLOSE", "EXEC", "ACCEPT")


def describe(prog):
    """What the parser understands of a program, as data (cobalto parse --json)."""
    return {
        "file": prog.path, "format": prog.fmt, "lines": len(prog.lines),
        "program_ids": [n for n, _ in prog.program_ids],
        "divisions": [{"name": d, "line": prog.tokens[i].line} for d, i in prog.divisions.items()],
        "sections": [{"division": d, "name": s, "line": prog.tokens[i].line}
                     for (d, s), i in prog.sections.items()],
        "files": [{"name": f, "status": v["status"], "records": list(v["records"])} for f, v in prog.files.items()],
        "data_items": [{"level": d.level, "name": d.name, "section": d.section} for d in prog.data_items],
        "procedure_using": [prog.tokens[i].text for i in prog.procedure_using] if prog.procedure_tok is not None else [],
        "paragraphs": [{"name": p.name, "section": bool(p.is_section), "line": p.line, "end_line": p.end_line}
                       for p in prog.paragraphs],
        "statements": [{"verb": s.verb, "line": s.line, "end_line": s.end_line,
                        "phrases": [p[0] for p in s.phrases], "terminated": bool(s.terminated)}
                       for s in prog.statements if s.verb in SITE_VERBS],
    }


def summary(prog):
    """Readable summary, for debugging: cobalto parse FILE."""
    L = [f"file: {prog.path}  format: {prog.fmt}  lines: {len(prog.lines)}  tokens: {len(prog.tokens)}",
         f"PROGRAM-ID: {', '.join(n for n, _ in prog.program_ids)}",
         "divisions: " + ", ".join(f"{d}@{prog.tokens[i].line}" for d, i in prog.divisions.items()),
         "sections: " + ", ".join(f"{d}/{s}@{prog.tokens[i].line}" for (d, s), i in prog.sections.items())]
    if prog.files:
        L.append("files: " + ", ".join(f"{f} (status {v['status']}, rec {','.join(v['records'])})" for f, v in prog.files.items()))
    ws = [d for d in prog.data_items if d.section in ("WORKING-STORAGE", "LINKAGE")]
    L.append("WS/LINKAGE items: " + ", ".join(f"{d.level} {d.name}" for d in ws[:60]) + (" ..." if len(ws) > 60 else ""))
    if prog.procedure_tok is not None:
        L.append("PROCEDURE DIVISION USING: " + " ".join(prog.tokens[i].text for i in prog.procedure_using))
    for p in prog.paragraphs:
        L.append(f"  {'SECTION   ' if p.is_section else 'paragraph '}{p.name:30s} lines {p.line}-{p.end_line}")
    for s in prog.statements:
        if s.verb in ("CALL", "READ", "WRITE", "REWRITE", "DELETE", "START", "OPEN", "CLOSE", "EXEC", "ACCEPT"):
            ph = " ".join(p[0] for p in s.phrases)
            L.append(f"  {s.verb:8s} lines {s.line}-{s.end_line}  tokens {s.start}-{s.end}"
                     + (f"  phrases: {ph}" if ph else "") + ("  [END-x]" if s.terminated else ""))
    return "\n".join(L)

