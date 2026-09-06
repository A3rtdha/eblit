"""Окно установки: те же чернила, что у Eblit. Не мастер с галочками и не консоль."""

from __future__ import annotations

import ctypes
import queue
import threading

from app.paths import icon_ico

INK = "#09090b"
LINE_HEX = "#1a1a1e"
TEXT = "#e6e6e8"
MUTE = "#6a6a70"
DIM = "#3a3a40"
LIVE = "#8aaeb4"
FAULT = "#c47a7a"

UI_FONT = "Segoe UI"


def available() -> bool:
    """Только импорт: root не пробуем, чтобы за установку создавался ровно один Tk."""
    try:
        import tkinter  # noqa: F401
    except (ImportError, RuntimeError):
        return False
    return True


class Window:
    """Шаги приходят из install через report() из рабочего потока; рисует главный поток."""

    def __init__(self, steps, log_file=None) -> None:
        import tkinter as tk

        self._tk = tk
        self.steps = list(steps)
        self.log_file = log_file
        self.queue: queue.Queue = queue.Queue()
        self.code = 1
        self.finished = False
        self.current = None
        self.dots: dict[str, object] = {}
        self.labels: dict[str, object] = {}
        self.done = 0
        self.last = ""

        self.root = tk.Tk()
        self.root.title("Eblit — установка")
        self.root.configure(bg=INK)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._try_close)

        wrap = tk.Frame(self.root, bg=INK)
        wrap.pack(fill="both", expand=True, padx=28, pady=24)

        tk.Label(wrap, text="Eblit", bg=INK, fg=TEXT, font=(UI_FONT, 22)).pack(anchor="w")
        self.status = tk.Label(
            wrap,
            text="Идёт установка",
            bg=INK,
            fg=LIVE,
            font=(UI_FONT, 12),
        )
        self.status.pack(anchor="w", pady=(6, 22))

        rows = tk.Frame(wrap, bg=INK)
        rows.pack(fill="x")
        for key, label in self.steps:
            row = tk.Frame(rows, bg=INK)
            row.pack(fill="x", pady=5)
            dot = tk.Canvas(row, width=8, height=8, bg=INK, highlightthickness=0)
            dot.pack(side="left", pady=4)
            self._paint_dot(dot, DIM)
            text = tk.Label(row, text=label, bg=INK, fg=DIM, font=(UI_FONT, 11), anchor="w")
            text.pack(side="left", fill="x", expand=True, padx=(10, 0))
            self.dots[key] = dot
            self.labels[key] = text

        self.detail = tk.Label(
            wrap,
            text="",
            bg=INK,
            fg=MUTE,
            font=(UI_FONT, 10),
            anchor="w",
            justify="left",
            wraplength=360,
        )
        self.detail.pack(fill="x", pady=(22, 10))

        self.bar = tk.Canvas(wrap, height=2, bg=LINE_HEX, highlightthickness=0)
        self.bar.pack(fill="x")
        self.fill = self.bar.create_rectangle(0, 0, 0, 2, fill=LIVE, width=0)

        self.foot = tk.Frame(wrap, bg=INK, height=36)
        self.foot.pack(fill="x", pady=(14, 0))
        self.foot.pack_propagate(False)

        self._chrome()
        self.root.update_idletasks()
        self._place(420, 520)

    def _paint_dot(self, canvas, color: str) -> None:
        canvas.delete("all")
        canvas.create_oval(1, 1, 7, 7, outline=color, fill=color)

    def _place(self, w: int, h: int) -> None:
        x = max(0, (self.root.winfo_screenwidth() - w) // 2)
        y = max(0, (self.root.winfo_screenheight() - h) // 2 - 36)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _chrome(self) -> None:
        try:
            ico = icon_ico()
            if str(ico).endswith(".ico") and ico.is_file():
                self.root.iconbitmap(default=str(ico))
        except Exception:
            pass
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            flag = ctypes.c_int(1)
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(flag), ctypes.sizeof(flag)
                ) == 0:
                    break
        except Exception:
            pass

    def report(self, kind: str, key: str = "", text: str = "") -> None:
        self.queue.put((kind, key, text))

    def run(self, job) -> int:
        def work() -> None:
            try:
                code = job(self.report)
                if code == 0:
                    self.report("done")
                else:
                    self.report("fail", "", f"установка вернула {code}")
            except Exception as exc:
                self.report("fail", "", str(exc) or exc.__class__.__name__)

        threading.Thread(target=work, name="eblit-setup", daemon=True).start()
        self.root.after(80, self._drain)
        self.root.mainloop()
        return self.code

    def _drain(self) -> None:
        try:
            while True:
                kind, key, text = self.queue.get_nowait()
                if kind == "step":
                    self._step(key)
                elif kind == "log":
                    self._detail(text)
                elif kind == "done":
                    self._done()
                elif kind == "fail":
                    self._fail(text)
        except queue.Empty:
            pass
        if not self.finished:
            self.root.after(80, self._drain)

    def _step(self, key: str) -> None:
        if self.current and self.current in self.dots:
            self._mark(self.current, LIVE, MUTE, filled=True)
            self.done += 1
        self.current = key
        if key in self.dots:
            self._mark(key, LIVE, TEXT, filled=True)
        self._bar()

    def _mark(self, key: str, dot: str, text_fg: str, *, filled: bool) -> None:
        canvas = self.dots[key]
        canvas.delete("all")
        if filled:
            canvas.create_oval(1, 1, 7, 7, outline=dot, fill=dot)
        else:
            canvas.create_oval(1, 1, 7, 7, outline=dot, fill=INK)
        self.labels[key].configure(fg=text_fg)

    def _detail(self, text: str) -> None:
        self.last = text
        self.detail.configure(text=text, fg=MUTE)

    def _bar(self, share: float | None = None) -> None:
        total = max(1, len(self.steps))
        part = share if share is not None else self.done / total
        width = self.bar.winfo_width() or 360
        self.bar.coords(self.fill, 0, 0, int(width * min(1.0, part)), 2)

    def _done(self) -> None:
        for key, _label in self.steps:
            self._mark(key, LIVE, MUTE, filled=True)
        self.current = None
        self.done = len(self.steps)
        self._bar(1.0)
        self.status.configure(text="Готово", fg=LIVE)
        self.detail.configure(text="готово", fg=LIVE)
        self.code = 0
        self.finished = True
        self.root.after(1200, self.root.destroy)

    def _fail(self, why: str) -> None:
        if self.current and self.current in self.dots:
            self._mark(self.current, FAULT, FAULT, filled=True)
        text = why or "не получилось"
        if self.log_file:
            text = f"{text}\nлог: {self.log_file}"
        self.status.configure(text="Не получилось", fg=FAULT)
        self.detail.configure(text=text, fg=FAULT)
        self.code = 1
        self.finished = True
        self._buttons()

    def _buttons(self) -> None:
        tk = self._tk
        copy = tk.Button(
            self.foot,
            text="Скопировать",
            command=self._copy,
            bg=INK,
            fg=MUTE,
            activebackground=INK,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=(UI_FONT, 10),
            cursor="hand2",
            padx=0,
        )
        copy.pack(side="left")
        close = tk.Button(
            self.foot,
            text="Закрыть",
            command=self.root.destroy,
            bg=INK,
            fg=TEXT,
            activebackground=INK,
            activeforeground=LIVE,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=(UI_FONT, 10),
            cursor="hand2",
            padx=0,
        )
        close.pack(side="right")

    def _copy(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.detail.cget("text"))
        except self._tk.TclError:
            pass

    def _try_close(self) -> None:
        if self.finished:
            self.root.destroy()
            return
        self._detail("установка идёт — дождись конца")
