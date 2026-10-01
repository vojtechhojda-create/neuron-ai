#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEUTRON 2.1 – lokální AI agent v terminálu (offline, llama-cpp-python)

  pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
  pip install huggingface_hub prompt_toolkit      (volitelné: stahování modelů, našeptávač příkazů)

  models/   *.gguf modely          modules/  moduly (*.py s funkcí register(app))
  themes/   vlastní motivy (*.json)  chats/    uložené konverzace
"""
import os
import re
import sys
import json
import time
import random
import shutil
import textwrap
import threading
import itertools
import importlib.util
from datetime import datetime
from pathlib import Path

try:
    import msvcrt  # Windows
except ImportError:
    msvcrt = None

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.styles import Style as PTStyle
    HAVE_PTK = True
except Exception:
    HAVE_PTK = False

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
os.system("")  # zapne ANSI barvy ve Windows terminálu

VERSION = "2.1"
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
MODELS_DIR = BASE / "models"
CHATS_DIR = BASE / "chats"
THEMES_DIR = BASE / "themes"
MODULES_DIR = BASE / "modules"
SETTINGS_FILE = BASE / "settings.json"

RST = "\033[0m"
BLD = "\033[1m"
MARGIN = "  "
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


# ───────────────────────── barvy a motivy ─────────────────────────
def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def fgc(c):
    return f"\033[38;2;{c[0]};{c[1]};{c[2]}m"


def fg(h):
    return fgc(rgb(h))


def lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def vlen(s):
    return len(ANSI_RE.sub("", s))


def cols():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100


BUILTIN_THEMES = {
    "Neutron (oranžová)": dict(accent="#ff7a00", accent2="#ffd166", dim="#7c7c7c", ok="#7ddc7a", err="#ff5f5f", think="#6a6a6a"),
    "Oceán":              dict(accent="#22d3ee", accent2="#6366f1", dim="#6b7a8c", ok="#4ade80", err="#f87171", think="#5b6b7c"),
    "Fialová":            dict(accent="#a78bfa", accent2="#f472b6", dim="#7d7590", ok="#86efac", err="#fb7185", think="#6d6680"),
    "Matrix":             dict(accent="#22c55e", accent2="#bef264", dim="#3f6b4a", ok="#86efac", err="#f87171", think="#3a5a44"),
    "Západ slunce":       dict(accent="#fb7185", accent2="#fbbf24", dim="#8a7373", ok="#a3e635", err="#ef4444", think="#7a6666"),
    "Cyberpunk":          dict(accent="#ff2a6d", accent2="#05d9e8", dim="#6e6a8a", ok="#05ffa1", err="#ff2a6d", think="#5a5778"),
    "Aurora":             dict(accent="#34d399", accent2="#60a5fa", dim="#6b8280", ok="#a7f3d0", err="#fca5a5", think="#587070"),
    "Dracula":            dict(accent="#bd93f9", accent2="#ff79c6", dim="#6272a4", ok="#50fa7b", err="#ff5555", think="#565a7a"),
    "Nord":               dict(accent="#88c0d0", accent2="#81a1c1", dim="#6b7a94", ok="#a3be8c", err="#bf616a", think="#5b667a"),
    "Gruvbox":            dict(accent="#fabd2f", accent2="#fe8019", dim="#928374", ok="#b8bb26", err="#fb4934", think="#7c6f64"),
    "Mono":               dict(accent="#f5f5f5", accent2="#737373", dim="#737373", ok="#d4d4d4", err="#ffffff", think="#525252"),
}


class Theme:
    def __init__(self, name, d):
        self.name = name
        self.d = d
        self.c1 = rgb(d["accent"])
        self.c2 = rgb(d.get("accent2", d["accent"]))
        self.a = fg(d["accent"])
        self.b = fg(d.get("accent2", d["accent"]))
        self.dim = fg(d.get("dim", "#777777"))
        self.ok = fg(d.get("ok", "#7ddc7a"))
        self.err = fg(d.get("err", "#ff5f5f"))
        self.think = fg(d.get("think", "#666666"))
        self.code = fg(d.get("code", d.get("accent2", d["accent"])))


T = None


def all_themes():
    th = dict(BUILTIN_THEMES)
    if THEMES_DIR.exists():
        for f in sorted(THEMES_DIR.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                th[d.get("name", f.stem)] = d
            except Exception:
                pass
    return th


def set_theme(name):
    global T
    th = all_themes()
    if name not in th:
        name = next(iter(BUILTIN_THEMES))
    T = Theme(name, th[name])


def gradient(text, row=0, rows=1, width=None):
    width = width or max(len(text), 1)
    out = []
    for j, ch in enumerate(text):
        if ch == " ":
            out.append(ch)
            continue
        t = (j / width) * 0.75 + (row / max(rows, 1)) * 0.25
        out.append(fgc(lerp(T.c1, T.c2, t)) + ch)
    return "".join(out) + RST


# ───────────────────────── prvky vzhledu ─────────────────────────
_LETTERS = {
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "U": ["██╗   ██╗", "██║   ██║", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "R": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
}

TIPS = [
    "End nebo Esc zastaví generování i celý /goal",
    "/theme změní barvy hned, bez restartu",
    "/goal napiš jednoduchý web do složky web – AI pracuje samo",
    "Vlastní modul = soubor v modules/ s funkcí register(app)",
    "/persona přepne styl odpovědí (programátor, učitel, překladatel…)",
    "/export uloží konverzaci jako HTML stránku v barvách tvého motivu",
    "/clip pošle obsah schránky modelu",
    "Řádek končící \\ pokračuje na další řádek",
    "Do themes/ dej vlastní .json motiv – vzor je midnight.json",
]


def banner_lines():
    rows = ["".join(_LETTERS[c][i] for c in "NEUTRON") for i in range(6)]
    width = len(rows[0])
    if cols() < width + 4:
        return [gradient("◆ N E U T R O N", 0, 1)]
    return [gradient(r, i, len(rows), width) for i, r in enumerate(rows)]


def box(title, lines, color=None):
    color = color or T.dim
    w = max([vlen(l) for l in lines] + [vlen(title) + 4]) + 2
    out = [f"{color}╭─ {T.b}{title}{color} " + "─" * (w - vlen(title) - 3) + f"╮{RST}"]
    for l in lines:
        out.append(f"{color}│{RST} {l}" + " " * (w - vlen(l) - 1) + f"{color}│{RST}")
    out.append(f"{color}╰" + "─" * w + f"╯{RST}")
    return out


def ctx_bar(frac, width=10):
    frac = max(0.0, min(1.0, frac))
    n = round(frac * width)
    color = T.ok if frac < 0.6 else (T.b if frac < 0.85 else T.err)
    return color + "▰" * n + T.dim + "▱" * (width - n) + RST


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def menu(title, options, start=0):
    """Šipky + Enter, Esc = zpět. Vrací index nebo None."""
    print(f"{MARGIN}{T.a}{BLD}{title}{RST}")
    if msvcrt is None:
        for i, o in enumerate(options, 1):
            print(f"{MARGIN}  {i}) {ANSI_RE.sub('', o)}")
        try:
            n = int(input(f"{MARGIN}Číslo (Enter = zpět): ").strip())
            return n - 1 if 1 <= n <= len(options) else None
        except ValueError:
            return None
    idx, first = start, True
    while True:
        if not first:
            sys.stdout.write(f"\033[{len(options)}A")
        first = False
        for i, o in enumerate(options):
            line = f"{MARGIN}{T.a}❯ {RST}{o}" if i == idx else f"{MARGIN}  {T.dim}{ANSI_RE.sub('', o)}"
            sys.stdout.write("\r\033[K" + line + RST + "\n")
        sys.stdout.flush()
        k = msvcrt.getwch()
        if k in ("\x00", "\xe0"):
            k2 = msvcrt.getwch()
            if k2 == "H":
                idx = (idx - 1) % len(options)
            elif k2 == "P":
                idx = (idx + 1) % len(options)
        elif k == "\r":
            return idx
        elif k == "\x1b":
            return None
        elif k == "\x03":
            raise KeyboardInterrupt


def stop_pressed():
    """True, když uživatel stiskl End nebo Esc (jen Windows)."""
    if msvcrt is None:
        return False
    hit = False
    while msvcrt.kbhit():
        k = msvcrt.getwch()
        if k == "\x1b":
            hit = True
        elif k in ("\x00", "\xe0"):
            if msvcrt.getwch() == "O":  # End
                hit = True
    return hit


class Spinner:
    """Animace při čekání na první token; hlídá End/Esc."""
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, label):
        self.label = label
        self.hit = False
        self._stop = threading.Event()
        self._t = None

    def _run(self):
        t0, i = time.time(), 0
        while not self._stop.is_set():
            if stop_pressed():
                self.hit = True
            hint = "zastavuji…" if self.hit else "End = zastavit"
            sys.stdout.write(f"\r{MARGIN}{T.a}{self.FRAMES[i % len(self.FRAMES)]}{RST} {T.dim}{self.label} "
                             f"{time.time() - t0:4.1f}s · {hint}{RST}\033[K")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)

    def start(self):
        stop_pressed()  # zahoď starý vstup
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self):
        self._stop.set()
        if self._t:
            self._t.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


# ───────────────────────── vykreslování odpovědi ─────────────────────────
class Renderer:
    """Streamovaný zalamovač textu s postranním pruhem, mini-markdownem a bloky kódu."""

    def __init__(self):
        self.width = max(40, min(cols() - 6, 110))
        self.col = 0
        self.at_line_start = True
        self.first_word = True
        self.pending_space = False
        self.word = ""
        self.bold = False
        self.icode = False
        self.heading = False
        self.think = False
        self.indent = 0
        self.in_block = False
        self.cbuf = ""
        self.label_capture = False
        self.label = ""
        self.any_out = False
        self.last_blank = True

    # --- nízká úroveň ---
    def _w(self, s):
        sys.stdout.write(s)
        sys.stdout.flush()

    def _bar(self):
        if self.in_block:
            return T.dim + "│" + RST
        if self.think:
            return T.think + "┆" + RST
        return T.a + "▎" + RST

    def _gutter(self):
        return MARGIN + self._bar() + " "

    def _reset_line(self):
        self.col = 0
        self.at_line_start = True
        self.first_word = True
        self.pending_space = False
        self.heading = False
        self.indent = 0
        self.bold = False
        self.icode = False

    def _start_line(self):
        if self.at_line_start:
            self._w(self._gutter() + " " * self.indent)
            self.col = self.indent
            self.at_line_start = False
            self.any_out = True
            self.last_blank = False

    def _wrap_break(self):
        self._w("\n")
        self.col = 0
        self.at_line_start = True
        self.pending_space = False

    def _nl(self):
        if self.at_line_start:
            if self.any_out and not self.last_blank:
                self._w(MARGIN + self._bar() + "\n")
                self.last_blank = True
        else:
            self._w("\n")
            self.last_blank = False
        self._reset_line()

    def _style(self, bold, code):
        s = ""
        if self.think:
            s += T.think
        if self.heading:
            s += T.b + BLD
        if bold:
            s += BLD + T.b
        if code and not self.think:
            s += "\033[48;5;236m" + T.code
        return s

    # --- veřejné API ---
    def write(self, text, think=False):
        if think != self.think:
            self._flush_word("\n")
            if not self.at_line_start:
                self._nl()
            self.think = think
        for ch in text:
            self._ch(ch)

    def finish(self):
        self._flush_word("\n")
        if self.in_block:
            if self.cbuf:
                self._code_line(self.cbuf)
                self.cbuf = ""
            self._w(MARGIN + T.dim + "╰" + "─" * 43 + RST + "\n")
            self.in_block = False
        elif not self.at_line_start:
            self._w("\n")
        self._reset_line()

    # --- zpracování znaků ---
    def _ch(self, ch):
        if ch == "\r":
            return
        if self.in_block:
            self._code_ch(ch)
            return
        if self.label_capture:
            if ch == "\n":
                self.label_capture = False
                self._open_block(self.label)
            else:
                self.label += ch
            return
        if ch == "\n":
            self._flush_word("\n")
            self._nl()
        elif ch in " \t":
            self._flush_word(" ")
        else:
            self.word += ch

    def _flush_word(self, term):
        w, self.word = self.word, ""
        if not w:
            if term == " " and not self.at_line_start:
                self.pending_space = True
            return
        bullet = numbered = False
        if self.first_word:
            if w.startswith("```"):
                self.first_word = False
                self.label = w[3:]
                if term == "\n":
                    self._open_block(self.label)
                else:
                    self.label_capture = True
                    self.label += " "
                return
            if term == " " and re.fullmatch(r"#{1,4}", w):
                self.heading = True
                self.first_word = False
                return
            if term == " " and w in ("-", "*", "+"):
                w, bullet = "•", True
            elif term == " " and re.fullmatch(r"\d{1,2}[.)]", w):
                numbered = True
        segs = [(w, False, False)] if bullet else self._parse(w)
        vis = sum(len(t) for t, _, _ in segs)
        need = vis + (1 if self.pending_space and not self.at_line_start else 0)
        if not self.at_line_start and self.col + need > self.width and self.col > self.indent:
            self._wrap_break()
        self._start_line()
        if self.pending_space and self.col > self.indent:
            self._w(" ")
            self.col += 1
        for t, b, c in segs:
            self._w(self._style(b, c) + t + RST)
            self.col += len(t)
        self.pending_space = term == " "
        self.first_word = False
        if bullet:
            self.indent = 2
        elif numbered:
            self.indent = len(w) + 1

    def _parse(self, w):
        out = []
        for part in re.split(r"(\*\*|`)", w):
            if part == "**":
                self.bold = not self.bold
            elif part == "`":
                self.icode = not self.icode
            elif part:
                out.append((part, self.bold, self.icode))
        return out

    # --- bloky kódu ---
    def _open_block(self, label):
        label = label.strip() or "kód"
        self._w(MARGIN + T.dim + "╭─ " + T.b + label + T.dim + " " + "─" * max(4, 40 - len(label)) + RST + "\n")
        self.in_block = True
        self.cbuf = ""
        self.any_out = True
        self.last_blank = False
        self._reset_line()

    def _code_ch(self, ch):
        if ch == "\n":
            line, self.cbuf = self.cbuf, ""
            if line.strip().startswith("```"):
                self.in_block = False
                self._w(MARGIN + T.dim + "╰" + "─" * 43 + RST + "\n")
                self._reset_line()
            else:
                self._code_line(line)
        else:
            self.cbuf += ch

    def _code_line(self, line):
        line = line.replace("\t", "    ")
        w = self.width - 2
        chunks = [line[i:i + w] for i in range(0, len(line), w)] or [""]
        for c in chunks:
            self._w(MARGIN + T.dim + "│ " + RST + T.code + c + RST + "\n")


# ───────────────────────── nastavení ─────────────────────────
DEFAULTS = {
    "last_model": "",
    "theme": "Neutron (oranžová)",
    "persona": "Výchozí",
    "workdir": "",
    "n_ctx": 4096,
    "n_gpu_layers": 0,
    "n_threads": max(1, (os.cpu_count() or 4) // 2),
    "temperature": 0.7,
    "max_tokens": 1024,
    "goal_steps": 20,
    "tools": True,
    "show_think": True,
    "animate": True,
    "disabled_modules": [],
    "system_prompt": (
        "Jsi Neutron, užitečný AI asistent běžící lokálně na počítači uživatele. "
        "Odpovídej stručně, věcně a česky, pokud uživatel nepíše jinak. "
        "Pro formátování používej jednoduchý markdown (**tučně**, `kód`, seznamy s pomlčkou, bloky ```)."
    ),
}

DOWNLOADS = [
    ("Qwen2.5 3B Instruct  (~2 GB, rychlý, slabší čeština)", "Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q4_k_m.gguf"),
    ("Qwen2.5 7B Instruct  (~4.7 GB, lepší, chce 8+ GB RAM)", "bartowski/Qwen2.5-7B-Instruct-GGUF", "Qwen2.5-7B-Instruct-Q4_K_M.gguf"),
]

TOOL_RE = re.compile(r'<tool\s+name="([^"]+)"(?:\s+arg="([^"]*)")?\s*(?:/>|>(.*?)</tool>)', re.S)
DONE_RE = re.compile(r"<done>(.*?)(?:</done>|$)", re.S)
STARTS = {"<think>": "think", "<tool": "tool", "<done>": "done"}


def partial_len(buf, tags):
    """Délka nejdelšího konce bufferu, který je začátkem některého z tagů."""
    m = max(len(t) for t in tags) - 1
    for k in range(min(m, len(buf)), 0, -1):
        if any(t.startswith(buf[-k:]) and len(t) > k for t in tags):
            return k
    return 0


def load_settings():
    s = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return s


# ───────────────────────── aplikace ─────────────────────────
class App:
    def __init__(self):
        self.s = load_settings()
        set_theme(self.s["theme"])
        self.llm = None
        self.model_path = None
        self.messages = []
        self.commands = {}
        self.tools = {}
        self.prompt_hooks = []
        self.modules = []
        self.auto_approve = False
        self.running = True
        self.ctx_used = 0
        self.last_tps = 0.0
        self.session = None
        self.base = BASE
        self.menu = menu
        self.box = box
        self.workdir = Path(self.s["workdir"]).expanduser() if self.s["workdir"] else Path.cwd()

    # ---- API pro moduly ----
    @property
    def theme(self):
        return T

    def add_command(self, name, fn, help=""):
        """fn(app, arg) – volá se na /name arg"""
        self.commands[name.lower()] = (fn, help)

    def add_tool(self, name, fn, help="", dangerous=False):
        """fn(app, arg, body) -> str – AI ho volá značkou <tool name=... arg=...>body</tool>"""
        self.tools[name] = dict(fn=fn, help=help, dangerous=dangerous)

    def add_prompt_hook(self, fn):
        """fn(app) -> str|None – text, který se připojí k systémovému promptu"""
        self.prompt_hooks.append(fn)

    def resolve(self, p):
        root = self.workdir.resolve()
        full = (root / p).resolve()
        if full != root and root not in full.parents:
            raise ValueError("cesta je mimo pracovní složku")
        return full

    def save(self):
        SETTINGS_FILE.write_text(json.dumps(self.s, ensure_ascii=False, indent=2), encoding="utf-8")

    def say(self, msg, kind="dim"):
        print(f"{MARGIN}{getattr(T, kind)}{msg}{RST}")

    def ask(self, text, steps=4):
        """Pošle zprávu modelu (pro moduly a příkazy)."""
        self.messages.append({"role": "user", "content": text})
        self.agent(steps)
        self.update_ctx()

    def refresh_system(self):
        if self.messages:
            self.messages[0]["content"] = self.build_system()

    # ---- moduly ----
    def load_modules(self):
        MODULES_DIR.mkdir(exist_ok=True)
        self.modules = []
        for f in sorted(MODULES_DIR.glob("*.py")):
            if f.name.startswith("_"):
                continue
            info = dict(id=f.stem, name=f.stem, desc="", ok=False, enabled=f.stem not in self.s["disabled_modules"], error="")
            if info["enabled"]:
                try:
                    spec = importlib.util.spec_from_file_location(f"neutron_mod_{f.stem}", f)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    info["name"] = getattr(mod, "NAME", f.stem)
                    info["desc"] = getattr(mod, "DESCRIPTION", "")
                    mod.register(self)
                    info["ok"] = True
                except Exception as e:
                    info["error"] = str(e)
            self.modules.append(info)

    # ---- model ----
    def list_models(self):
        MODELS_DIR.mkdir(exist_ok=True)
        return sorted(MODELS_DIR.rglob("*.gguf"))

    def download_model(self):
        try:
            from huggingface_hub import hf_hub_download
        except ImportError:
            self.say("Chybí huggingface_hub:  pip install huggingface_hub", "err")
            input("Enter…")
            return None
        i = menu("Který model stáhnout?", [d[0] for d in DOWNLOADS] + ["Zpět"])
        if i is None or i >= len(DOWNLOADS):
            return None
        _, repo, fname = DOWNLOADS[i]
        self.say(f"Stahuji {fname} …")
        try:
            return Path(hf_hub_download(repo_id=repo, filename=fname, local_dir=str(MODELS_DIR)))
        except Exception as e:
            self.say(f"Stažení selhalo: {e}", "err")
            input("Enter…")
            return None

    def choose_model(self):
        while True:
            self.header("výběr modelu", info=False)
            models = self.list_models()
            labels = [f"{m.name}  {T.dim}({m.stat().st_size / 1e9:.1f} GB){RST}" for m in models]
            labels += ["＋ Stáhnout model z internetu", "Konec"]
            i = menu("Vyber model:", labels)
            if i is None or i == len(labels) - 1:
                sys.exit(0)
            if i == len(labels) - 2:
                p = self.download_model()
                if p:
                    return p
                continue
            return models[i]

    def set_model_path(self, p):
        self.model_path = p
        try:
            self.s["last_model"] = str(p.relative_to(MODELS_DIR))
        except ValueError:
            self.s["last_model"] = str(p)
        self.save()

    def load_llm(self):
        try:
            from llama_cpp import Llama
        except ImportError:
            self.say("Chybí llama-cpp-python:\npip install llama-cpp-python --prefer-binary "
                     "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu", "err")
            sys.exit(1)
        sp = Spinner(f"načítám {self.model_path.name}")
        sp.start()
        t = time.time()
        try:
            self.llm = Llama(
                model_path=str(self.model_path),
                n_ctx=int(self.s["n_ctx"]),
                n_gpu_layers=int(self.s["n_gpu_layers"]),
                n_threads=int(self.s["n_threads"]),
                verbose=False,
            )
        finally:
            sp.stop()
        self.say(f"✔ Model připraven za {time.time() - t:.1f} s.", "ok")

    # ---- vzhled ----
    def header(self, sub="", info=True, animate=False):
        clear()
        print()
        for l in banner_lines():
            print(MARGIN + l)
            if animate:
                time.sleep(0.05)
        print(f"{MARGIN}{T.dim}v{VERSION} · lokální AI agent · 100% offline{(' · ' + sub) if sub else ''}{RST}\n")
        if info and self.model_path:
            n_tools = len(self.tools) if self.s["tools"] else 0
            lines = [
                f"{T.dim}model    {RST}{self.model_path.name}",
                f"{T.dim}složka   {RST}{self.workdir}",
                f"{T.dim}motiv    {RST}{T.b}{T.name}{RST}   {T.dim}persona {RST}{self.s['persona']}",
                f"{T.dim}výbava   {RST}{n_tools} nástrojů · {sum(1 for m in self.modules if m['ok'])} modulů · {len(self.commands)} příkazů",
            ]
            for l in box("Neutron", lines):
                print(MARGIN + l)
            print(f"\n{MARGIN}{T.dim}tip: {random.choice(TIPS)}{RST}\n")

    def toolbar(self):
        frac = self.ctx_used / max(int(self.s["n_ctx"]), 1)
        tps = f" · {self.last_tps:.0f} tok/s" if self.last_tps else ""
        name = self.model_path.name if self.model_path else "—"
        return (f" {T.a}◆{RST} {T.dim}{name}  {RST}{ctx_bar(frac)} {T.dim}{frac * 100:.0f}%{tps}"
                f" · {T.name} · End = stop · /help{RST} ")

    # ---- chat ----
    def build_system(self):
        p = self.s["system_prompt"]
        for h in self.prompt_hooks:
            try:
                extra = h(self)
                if extra:
                    p += "\n\n" + extra
            except Exception:
                pass
        if self.tools and self.s["tools"]:
            p += (
                "\n\nMáš k dispozici nástroje. Zavolej JEDEN nástroj na konci odpovědi přesně v tomto tvaru:\n"
                '<tool name="NÁZEV" arg="ARGUMENT">VOLITELNÝ TEXT</tool>\n'
                "Po zavolání odpověď ukonči a počkej na výsledek. Nástroje:\n"
            )
            for n, t in self.tools.items():
                p += f"- {n}: {t['help']}\n"
            p += f"Pracovní složka: {self.workdir}"
        return p

    def reset_chat(self):
        self.messages = [{"role": "system", "content": self.build_system()}]
        self.ctx_used = 0
        self.update_ctx()

    def count_tokens(self, text):
        try:
            return len(self.llm.tokenize(text.encode("utf-8"), add_bos=False)) + 8
        except Exception:
            return len(text) // 3 + 8

    def update_ctx(self):
        self.ctx_used = sum(self.count_tokens(m["content"]) for m in self.messages)

    def trim(self):
        limit = int(self.s["n_ctx"]) - int(self.s["max_tokens"]) - 64
        total = sum(self.count_tokens(m["content"]) for m in self.messages)
        while total > limit and len(self.messages) > 2:
            total -= self.count_tokens(self.messages.pop(1)["content"])

    def stream_reply(self):
        """Vrací (odpověď, zastaveno). Odpověď obsahuje i značky <tool>/<done> pro parser."""
        r = Renderer()
        show_think = self.s["show_think"]
        state = {"answer": "", "buf": "", "mode": None}

        def out(text, think=False):
            if not text:
                return
            if think:
                if show_think:
                    r.write(text, think=True)
            else:
                r.write(text)
                state["answer"] += text

        def feed(tok, final=False):
            state["buf"] += tok
            while state["buf"]:
                buf, mode = state["buf"], state["mode"]
                if mode in ("tool", "done"):
                    state["answer"] += buf
                    state["buf"] = ""
                    return
                if mode == "think":
                    i = buf.find("</think>")
                    if i >= 0:
                        out(buf[:i], True)
                        state["buf"], state["mode"] = buf[i + 8:], None
                        continue
                    hold = 0 if final else partial_len(buf, ["</think>"])
                    out(buf[:len(buf) - hold], True)
                    state["buf"] = buf[len(buf) - hold:]
                    return
                best = None
                for tag in STARTS:
                    i = buf.find(tag)
                    if i >= 0 and (best is None or i < best[0]):
                        best = (i, tag)
                if best:
                    i, tag = best
                    out(buf[:i])
                    state["buf"], state["mode"] = buf[i + len(tag):], STARTS[tag]
                    if state["mode"] in ("tool", "done"):
                        state["answer"] += tag
                    continue
                hold = 0 if final else partial_len(buf, list(STARTS))
                out(buf[:len(buf) - hold])
                state["buf"] = buf[len(buf) - hold:]
                return

        t0 = time.time()
        sp = Spinner("přemýšlím")
        sp.start()
        stopped, n_tok, t_first = False, 0, None
        stream = None
        try:
            stream = self.llm.create_chat_completion(
                messages=self.messages,
                temperature=float(self.s["temperature"]),
                max_tokens=int(self.s["max_tokens"]),
                stop=["</tool>"],
                stream=True,
            )
            it = iter(stream)
            first = next(it, None)
        except BaseException:
            sp.stop()
            raise
        sp.stop()
        if sp.hit:
            stopped = True
        elif first is not None:
            t_first = time.time()
            try:
                for chunk in itertools.chain([first], it):
                    tok = chunk["choices"][0]["delta"].get("content")
                    if tok:
                        n_tok += 1
                        feed(tok)
                    if stop_pressed():
                        stopped = True
                        break
                feed("", final=True)
            except KeyboardInterrupt:
                stopped = True
                feed("", final=True)
        r.finish()
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
        ans = state["answer"]
        if "<tool" in ans and "</tool>" not in ans and "/>" not in ans and not stopped:
            ans += "</tool>"
        gen = max(time.time() - (t_first or time.time()), 1e-6)
        tps = n_tok / gen if n_tok else 0.0
        if tps:
            self.last_tps = tps
        flag = f"  {T.err}■ zastaveno{RST}" if stopped else ""
        print(f"{MARGIN}{T.dim}└ {n_tok} tok · {tps:.1f} tok/s · {time.time() - t0:.1f} s{RST}{flag}")
        return ans.strip(), stopped

    def run_tool(self, name, arg, body):
        t = self.tools.get(name)
        if not t:
            return f"Neznámý nástroj '{name}'. Dostupné: {', '.join(self.tools)}"
        if t["dangerous"] and not self.auto_approve:
            print(f"{MARGIN}{T.b}⚡ {name}{RST} {arg}")
            for l in (body or "").strip().splitlines()[:4]:
                print(f"{MARGIN}{T.dim}  {l[:90]}{RST}")
            ans = input(f"{MARGIN}{T.a}povolit? {T.dim}[a]no  [n]e  [v]šechno{T.a} › {RST}").strip().lower()
            if ans in ("v", "vse", "vše"):
                self.auto_approve = True
            elif ans not in ("a", "ano", "y"):
                print(f"{MARGIN}{T.err}✖ zamítnuto{RST}")
                return "Uživatel akci zamítl."
        else:
            print(f"{MARGIN}{T.b}⚙ {name}{RST} {T.dim}{(arg or '')[:70]}{RST}")
        try:
            out = str(t["fn"](self, arg or "", (body or "").strip("\n")))
        except Exception as e:
            out = f"Chyba: {e}"
        lines = out.strip().splitlines() or [""]
        for l in lines[:3]:
            print(f"{MARGIN}{T.dim}└ {l[:100]}{RST}")
        if len(lines) > 3:
            print(f"{MARGIN}{T.dim}  … a dalších {len(lines) - 3} řádků{RST}")
        return out[:4000]

    def agent(self, max_steps=4, goal=False):
        idle = 0
        for step in range(1, max_steps + 1):
            self.trim()
            tag = f" {T.dim}· krok {step}/{max_steps}{RST}" if goal else ""
            print(f"{MARGIN}{T.a}{BLD}◆ Neutron{RST}{tag}")
            try:
                reply, stopped = self.stream_reply()
            except Exception as e:
                self.say(f"Chyba generování: {e}", "err")
                self.messages.pop()
                return
            self.messages.append({"role": "assistant", "content": reply or "(zastaveno)"})
            if stopped:
                return
            d = DONE_RE.search(reply)
            if goal and d:
                for l in box("Hotovo", textwrap.wrap(d.group(1).strip() or "Cíl splněn.", 70), T.ok):
                    print(MARGIN + l)
                return
            calls = TOOL_RE.findall(reply) if self.s["tools"] else []
            if not calls:
                if not goal:
                    return
                idle += 1
                if idle >= 3:
                    self.say("Model se zasekl (žádný nástroj ani <done>). Konec.", "err")
                    return
                self.messages.append({"role": "user", "content": "Pokračuj: zavolej nástroj, nebo napiš <done>shrnutí</done>, pokud je cíl splněn."})
                continue
            idle = 0
            name, arg, body = calls[0]
            result = self.run_tool(name, arg, body)
            self.messages.append({"role": "user", "content": f"[VÝSLEDEK NÁSTROJE {name}]\n{result}"})
            if stop_pressed():
                self.say("■ zastaveno", "err")
                return
            print()
        self.say(f"Dosažen limit {max_steps} kroků.")

    # ---- vstup ----
    def make_session(self):
        if not (HAVE_PTK and sys.stdin.isatty() and sys.stdout.isatty()):
            return None
        app = self

        class CmdCompleter(Completer):
            def get_completions(self, doc, event):
                t = doc.text_before_cursor
                if t.startswith("/") and " " not in t:
                    for n, (_, h) in sorted(app.commands.items()):
                        if ("/" + n).startswith(t.lower()):
                            yield Completion("/" + n, start_position=-len(t), display_meta=h)

        try:
            return PromptSession(
                history=FileHistory(str(BASE / ".neutron_history")),
                completer=CmdCompleter(),
                complete_while_typing=True,
                bottom_toolbar=lambda: ANSI(app.toolbar()),
                style=PTStyle.from_dict({"bottom-toolbar": "noreverse", "bottom-toolbar.text": "noreverse"}),
            )
        except Exception:
            return None

    def read_line(self, cont=False):
        if cont:
            msg = f"{MARGIN}{T.dim}… {RST}"
        else:
            msg = f"{MARGIN}{T.b}❯ {RST}"
        if self.session:
            return self.session.prompt(ANSI(msg))
        if not cont:
            frac = self.ctx_used / max(int(self.s["n_ctx"]), 1)
            print(f"{MARGIN}{T.dim}{'─' * (cols() - 6)}{RST}")
            print(f"{MARGIN}{T.dim}{self.model_path.name} · {RST}{ctx_bar(frac)} {T.dim}{frac * 100:.0f}% · End = stop · /help{RST}")
        return input(msg)

    # ---- příkazy ----
    def cmd_help(self, arg):
        print(f"{MARGIN}{T.a}{BLD}Příkazy{RST}")
        for n in sorted(self.commands):
            print(f"{MARGIN}  {T.b}/{n:<11}{RST}{T.dim}{self.commands[n][1]}{RST}")
        if self.tools:
            print(f"\n{MARGIN}{T.a}{BLD}Nástroje pro AI{RST} {T.dim}(⚡ = vyžaduje potvrzení){RST}")
            for n, t in self.tools.items():
                mark = f"{T.b}⚡" if t["dangerous"] else f"{T.dim}⚙"
                print(f"{MARGIN}  {mark} {n:<14}{RST}{T.dim}{t['help'][:70]}{RST}")
        print(f"\n{MARGIN}{T.dim}\\ na konci řádku = víceřádková zpráva · End/Esc = zastavit odpověď{RST}")

    def cmd_goal(self, arg):
        goal = arg or input(f"{MARGIN}{T.b}Cíl › {RST}").strip()
        if not goal:
            return
        if not self.tools or not self.s["tools"]:
            self.say("Bez nástrojů (modulů) nemá /goal čím pracovat – zapni je v /moduly.", "err")
            return
        for l in box("Cíl", textwrap.wrap(goal, 70), T.a):
            print(MARGIN + l)
        print()
        self.messages.append({"role": "user", "content": (
            f"CÍL: {goal}\nPracuj samostatně po krocích a používej nástroje. "
            "V každém kroku zavolej nejvýše jeden nástroj. Až je cíl splněn, odpověz <done>krátké shrnutí</done>.")})
        self.agent(max_steps=int(self.s["goal_steps"]), goal=True)
        self.update_ctx()

    def cmd_task(self, arg):
        p = Path(arg.strip().strip('"'))
        if not arg or not p.exists():
            self.say("Použití: /task cesta\\k\\souboru.txt", "err")
            return
        text = p.read_text(encoding="utf-8", errors="replace")
        self.say(f"Načteno {len(text)} znaků z {p.name}")
        self.ask(text)

    def cmd_clear(self, arg):
        self.reset_chat()
        self.header()

    def cmd_save(self, arg):
        CHATS_DIR.mkdir(exist_ok=True)
        f = CHATS_DIR / f"chat_{datetime.now():%Y%m%d_%H%M%S}.md"
        parts = [f"**{'Ty' if m['role'] == 'user' else 'Neutron'}**:\n\n{m['content']}\n" for m in self.messages[1:]]
        f.write_text("\n".join(parts), encoding="utf-8")
        self.say(f"✔ Uloženo: {f}", "ok")

    def cmd_model(self, arg):
        self.llm = None
        self.set_model_path(self.choose_model())
        self.header(self.model_path.name, info=False)
        self.load_llm()
        self.reset_chat()
        self.header()

    def cmd_folder(self, arg):
        if not arg:
            self.say(f"Pracovní složka: {self.workdir}")
            return
        p = Path(arg.strip('"')).expanduser()
        if not p.is_dir():
            self.say("Složka neexistuje.", "err")
            return
        self.workdir = p.resolve()
        self.s["workdir"] = str(self.workdir)
        self.save()
        self.refresh_system()
        self.say(f"✔ Pracovní složka: {self.workdir}", "ok")

    def cmd_theme(self, arg):
        names = list(all_themes())
        labels = []
        for n in names:
            d = all_themes()[n]
            sw = "".join(fgc(lerp(rgb(d["accent"]), rgb(d.get("accent2", d["accent"])), i / 9)) + "█" for i in range(10)) + RST
            labels.append(f"{sw}  {n}")
        clear()
        print()
        i = menu("Vyber barevný motiv (Esc = zpět):", labels, start=names.index(T.name) if T.name in names else 0)
        if i is not None:
            self.s["theme"] = names[i]
            self.save()
            set_theme(names[i])
        self.header()

    def cmd_modules(self, arg):
        while True:
            clear()
            print()
            labels = []
            for m in self.modules:
                st = f"{T.ok}[x]{RST}" if m["enabled"] else f"{T.dim}[ ]{RST}"
                err = f" {T.err}chyba: {m['error']}{RST}" if m["error"] else ""
                labels.append(f"{st} {m['name']} {T.dim}– {m['desc']}{RST}{err}")
            if not labels:
                self.say("Složka modules/ je prázdná.")
                input("Enter…")
                break
            i = menu("Moduly – Enter zapne/vypne (po restartu), Esc = zpět:", labels)
            if i is None:
                break
            mid = self.modules[i]["id"]
            dis = self.s["disabled_modules"]
            if mid in dis:
                dis.remove(mid)
            else:
                dis.append(mid)
            self.modules[i]["enabled"] = mid not in dis
            self.save()
        self.header()

    def cmd_settings(self, arg):
        reload_needed = False
        items = [
            ("Teplota", "temperature", float, False),
            ("Max. tokenů odpovědi", "max_tokens", int, False),
            ("Max. kroků pro /goal", "goal_steps", int, False),
            ("Kontext n_ctx (reload)", "n_ctx", int, True),
            ("GPU vrstvy, -1 = všechny (reload)", "n_gpu_layers", int, True),
            ("Vlákna CPU (reload)", "n_threads", int, True),
            ("Systémový prompt", "system_prompt", str, False),
            ("Nástroje zapnuty", "tools", bool, False),
            ("Zobrazovat <think>", "show_think", bool, False),
            ("Animace loga", "animate", bool, False),
        ]
        while True:
            clear()
            print()
            labels = [f"{n}: {T.dim}{str(self.s[k])[:50]}{RST}" for n, k, _, _ in items] + ["Zpět"]
            i = menu("Nastavení:", labels)
            if i is None or i == len(items):
                break
            name, key, typ, rl = items[i]
            if typ is bool:
                self.s[key] = not self.s[key]
            else:
                v = input(f"{MARGIN}{name} [{self.s[key]}]: ").strip()
                if v:
                    try:
                        self.s[key] = typ(v)
                    except ValueError:
                        self.say("Neplatná hodnota.", "err")
                        time.sleep(1)
                        continue
            reload_needed = reload_needed or rl
            self.save()
        if reload_needed:
            self.llm = None
            self.load_llm()
        self.refresh_system()
        self.update_ctx()
        self.header()

    def cmd_exit(self, arg):
        self.running = False

    # ---- start ----
    def boot(self):
        for n, f, h in [
            ("help", self.cmd_help, "nápověda, příkazy a nástroje"),
            ("goal", self.cmd_goal, "AI pracuje samo, dokud není cíl splněn"),
            ("task", self.cmd_task, "pošle obsah souboru jako zprávu"),
            ("theme", self.cmd_theme, "barevný motiv"),
            ("moduly", self.cmd_modules, "zapnout/vypnout moduly"),
            ("folder", self.cmd_folder, "pracovní složka pro nástroje"),
            ("model", self.cmd_model, "změnit model"),
            ("nastaveni", self.cmd_settings, "teplota, kontext, GPU, prompt…"),
            ("clear", self.cmd_clear, "nová konverzace"),
            ("save", self.cmd_save, "uloží konverzaci do chats/ (markdown)"),
            ("exit", self.cmd_exit, "konec"),
        ]:
            self.add_command(n, lambda app, a, f=f: f(a), h)
        self.load_modules()
        p = (MODELS_DIR / self.s["last_model"]) if self.s["last_model"] else None
        if not p or not p.exists():
            p = self.choose_model()
        self.set_model_path(p)
        self.header(self.model_path.name, info=False, animate=self.s["animate"])
        self.load_llm()
        self.reset_chat()
        self.header()
        for m in self.modules:
            if m["error"]:
                self.say(f"Modul {m['id']} se nenačetl: {m['error']}", "err")
        self.session = self.make_session()

    def run(self):
        self.boot()
        while self.running:
            try:
                line = self.read_line().rstrip()
                while line.endswith("\\"):
                    line = line[:-1] + "\n" + self.read_line(cont=True).rstrip()
            except (KeyboardInterrupt, EOFError):
                print()
                break
            if not line.strip():
                continue
            if line.startswith("/"):
                name, _, arg = line[1:].partition(" ")
                cmd = self.commands.get(name.lower())
                if not cmd:
                    self.say("Neznámý příkaz. /help", "err")
                    continue
                try:
                    cmd[0](self, arg.strip())
                except (KeyboardInterrupt, EOFError):
                    print()
                except Exception as e:
                    self.say(f"Chyba příkazu: {e}", "err")
                continue
            print()
            self.ask(line)
            print()
        self.say("Nashledanou.")


if __name__ == "__main__":
    App().run()
