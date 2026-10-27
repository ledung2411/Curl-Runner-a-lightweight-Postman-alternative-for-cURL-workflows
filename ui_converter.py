# ui_converter.py - String / JSON converter utility
# type: ignore
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
from typing import Any, TYPE_CHECKING

from constants import (
    BG, BG2, BG3, BORDER, ACCENT, ACCENT2, TEXT, TEXT_DIM,
    ACTIVE_TEXT, GREEN, RED_C, TITLEBAR_BG, FONT_FAMILY, FONT_FAMILY_MONO,
    SURFACE_HOVER,
)
from ui_theme import apply_modern_theme

if TYPE_CHECKING:
    from app import CurlRunnerApp


class ConverterWindow(tk.Toplevel):
    """Convert between JSON, text, and escaped JSON string literals."""

    MODES = (
        ("json_pretty", "JSON Pretty"),
        ("json_minify", "JSON Minify"),
        ("to_json_string", "Input -> JSON string"),
        ("from_json_string", "JSON string -> Text/JSON"),
        ("lines_to_array", "Lines -> JSON array"),
    )

    def __init__(self, parent: "CurlRunnerApp", initial_text: str = ""):
        super().__init__(parent)
        self.parent_app = parent
        self.title("Convert String / JSON")
        self.geometry("1120x720")
        self.minsize(820, 520)
        self.configure(bg=BG)
        apply_modern_theme(self)

        self.mode_var = tk.StringVar(value=self.MODES[0][0])
        self._setup_fonts()
        self._build_ui()
        if initial_text:
            self.input_tw.insert("1.0", initial_text)

    def _setup_fonts(self) -> None:
        self.fn_title = tkfont.Font(family=FONT_FAMILY, size=13, weight="bold")
        self.fn_label = tkfont.Font(family=FONT_FAMILY, size=9)
        self.fn_btn = tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")
        self.fn_badge = tkfont.Font(family=FONT_FAMILY, size=8, weight="bold")
        self.fn_small = tkfont.Font(family=FONT_FAMILY, size=8)
        self.fn_mono = tkfont.Font(family=FONT_FAMILY_MONO, size=10)

    def _build_ui(self) -> None:
        tb = tk.Frame(self, bg=TITLEBAR_BG, height=54)
        tb.pack(fill="x", side="top")
        tb.pack_propagate(False)
        tk.Label(tb, text="Convert String / JSON", font=self.fn_title,
                 bg=TITLEBAR_BG, fg=TEXT).pack(side="left", padx=14, pady=12)

        tk.Label(tb, text="Mode:", font=self.fn_small,
                 bg=TITLEBAR_BG, fg=TEXT_DIM).pack(side="left", padx=(10, 4))
        mode_cb = ttk.Combobox(
            tb,
            textvariable=self.mode_var,
            values=[label for _, label in self.MODES],
            state="readonly",
            width=26,
            font=self.fn_label,
        )
        mode_cb.pack(side="left")
        mode_cb.bind("<<ComboboxSelected>>", self._on_mode_label_selected)
        mode_cb.set(self.MODES[0][1])

        self._mkbtn(tb, "Convert", self.convert, side="left", pad=(8, 0), primary=True)
        self._mkbtn(tb, "Beautify", self.beautify, side="left", pad=(6, 0))
        self._mkbtn(tb, "Swap", self.swap, side="left", pad=(6, 0))
        self._mkbtn(tb, "Copy Output", self.copy_output, side="left", pad=(6, 0))
        self._mkbtn(tb, "Clear", self.clear, side="left", pad=(6, 0))
        self._mkbtn(tb, "Load Response", self.load_response, side="right", pad=(0, 12))

        body = tk.PanedWindow(self, orient="horizontal", bg=BORDER,
                              sashwidth=6, sashrelief="flat", bd=0)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        left = self._build_panel(body, "INPUT")
        right = self._build_panel(body, "OUTPUT")
        self.input_tw = left["text"]
        self.output_tw = right["text"]
        body.add(left["frame"], minsize=320)
        body.add(right["frame"], minsize=320)

        self.status_lbl = tk.Label(self, text="", font=self.fn_label,
                                   bg=BG, fg=TEXT_DIM, anchor="w")
        self.status_lbl.pack(fill="x", padx=12, pady=(0, 8))

    def _build_panel(self, parent: tk.Widget, title: str) -> dict[str, Any]:
        frame = tk.Frame(parent, bg=BG)
        tk.Label(frame, text=title, font=self.fn_badge,
                 bg=BG, fg=TEXT_DIM, anchor="w").pack(fill="x", pady=(0, 4))
        wrap = tk.Frame(frame, bg=BORDER)
        wrap.pack(fill="both", expand=True)
        tw = tk.Text(
            wrap, bg=BG2, fg=TEXT, font=self.fn_mono,
            wrap="char", relief="flat", padx=10, pady=8,
            insertbackground=ACCENT, selectbackground=ACCENT,
            selectforeground=ACTIVE_TEXT, undo=True, bd=0,
        )
        sb_y = tk.Scrollbar(wrap, command=tw.yview, bg=BG3, troughcolor=BG2, bd=0)
        tw.configure(yscrollcommand=sb_y.set)
        sb_y.pack(side="right", fill="y")
        tw.pack(fill="both", expand=True, padx=1, pady=1)
        return {"frame": frame, "text": tw}

    def _mkbtn(
        self,
        parent: tk.Widget,
        text: str,
        cmd,
        side: str = "left",
        pad: tuple[int, int] = (0, 0),
        primary: bool = False,
    ) -> tk.Button:
        bg = ACCENT if primary else BG3
        fg = ACTIVE_TEXT if primary else TEXT
        active_bg = ACCENT2 if primary else SURFACE_HOVER
        b = tk.Button(parent, text=text, font=self.fn_label,
                      bg=bg, fg=fg, activebackground=active_bg,
                      activeforeground=fg, relief="flat", cursor="hand2",
                      padx=11, pady=5, command=cmd, bd=0)
        if not primary:
            b.bind("<Enter>", lambda _e: b.config(bg=SURFACE_HOVER) if str(b["state"]) == "normal" else None)
            b.bind("<Leave>", lambda _e: b.config(bg=BG3) if str(b["state"]) == "normal" else None)
        b.pack(side=side, padx=pad)
        return b

    def _on_mode_label_selected(self, _event=None) -> None:
        self.status_lbl.config(text="")

    def _mode(self) -> str:
        raw = self.mode_var.get()
        labels = {label: key for key, label in self.MODES}
        return labels.get(raw, raw)

    def _set_output(self, text: str) -> None:
        self.output_tw.delete("1.0", "end")
        self.output_tw.insert("1.0", text)

    def _set_status(self, text: str, ok: bool = True) -> None:
        self.status_lbl.config(text=text, fg=GREEN if ok else RED_C)

    def convert(self) -> None:
        raw = self.input_tw.get("1.0", "end-1c")
        try:
            mode = self._mode()
            if mode == "json_pretty":
                out = json.dumps(json.loads(raw), indent=2, ensure_ascii=False, sort_keys=False)
            elif mode == "json_minify":
                out = json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
            elif mode == "to_json_string":
                out = json.dumps(raw, ensure_ascii=False)
            elif mode == "from_json_string":
                out = self._from_json_string(raw)
            elif mode == "lines_to_array":
                lines = raw.splitlines()
                out = json.dumps(lines, indent=2, ensure_ascii=False)
            else:
                raise ValueError(f"Unknown convert mode: {mode}")
            self._set_output(out)
            self._set_status(f"Converted · input {len(raw):,} chars · output {len(out):,} chars")
        except Exception as exc:
            self._set_status(f"Convert failed: {exc}", ok=False)

    def beautify(self) -> None:
        raw = self.input_tw.get("1.0", "end-1c")
        try:
            out = self._beautify_json_or_string(raw)
            self._set_output(out)
            self._set_status(f"Beautified · input {len(raw):,} chars · output {len(out):,} chars")
        except Exception as exc:
            self._set_status(f"Beautify failed: {exc}", ok=False)

    def _beautify_json_or_string(self, raw: str) -> str:
        text = raw.strip()
        if not text:
            return ""
        try:
            value = json.loads(text)
            if isinstance(value, str):
                try:
                    return json.dumps(json.loads(value), indent=2, ensure_ascii=False)
                except Exception:
                    return value
            return json.dumps(value, indent=2, ensure_ascii=False)
        except Exception:
            pass

        unescaped = self._from_json_string(text)
        try:
            return json.dumps(json.loads(unescaped), indent=2, ensure_ascii=False)
        except Exception:
            return unescaped

    def _from_json_string(self, raw: str) -> str:
        text = raw.strip()
        value: Any
        try:
            value = json.loads(text)
        except Exception:
            try:
                value = json.loads(f'"{text}"')
            except Exception:
                # backslashreplace giữ ký tự ngoài latin-1 (tiếng Việt, emoji) dưới dạng \uXXXX
                # để unicode_escape giải mã lại đúng, thay vì biến thành mojibake.
                value = text.encode("latin-1", "backslashreplace").decode("unicode_escape")

        if not isinstance(value, str):
            return json.dumps(value, indent=2, ensure_ascii=False)

        inner = value
        try:
            parsed_inner = json.loads(inner)
            return json.dumps(parsed_inner, indent=2, ensure_ascii=False)
        except Exception:
            return inner

    def swap(self) -> None:
        left = self.input_tw.get("1.0", "end-1c")
        right = self.output_tw.get("1.0", "end-1c")
        self.input_tw.delete("1.0", "end")
        self.input_tw.insert("1.0", right)
        self.output_tw.delete("1.0", "end")
        self.output_tw.insert("1.0", left)
        self._set_status("Swapped input/output")

    def copy_output(self) -> None:
        out = self.output_tw.get("1.0", "end-1c")
        if not out:
            messagebox.showinfo("", "Output đang trống.", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(out)
        self._set_status("Output copied to clipboard")

    def clear(self) -> None:
        self.input_tw.delete("1.0", "end")
        self.output_tw.delete("1.0", "end")
        self.status_lbl.config(text="")

    def load_response(self) -> None:
        tab = None
        if getattr(self.parent_app, "active_tab_idx", -1) >= 0:
            tab = self.parent_app.tabs[self.parent_app.active_tab_idx]
        text = getattr(tab, "body_text", "") if tab is not None else ""
        if not text:
            messagebox.showinfo("", "Chưa có response body để load.", parent=self)
            return
        self.input_tw.delete("1.0", "end")
        self.input_tw.insert("1.0", text)
        self._set_status("Loaded active response body")
