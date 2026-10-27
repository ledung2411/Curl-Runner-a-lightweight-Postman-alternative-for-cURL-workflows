# ui_ollama_setup.py - Ollama install/setup helper for local AI analysis
# type: ignore
from __future__ import annotations

import os
import subprocess
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox, font as tkfont
from typing import TYPE_CHECKING, Callable, Any

from constants import (
    BG, BG2, BG3, BORDER, ACCENT, TEXT, TEXT_DIM,
    ACTIVE_TEXT, GREEN, RED_C, YELLOW_C,
    SURFACE_HOVER, TITLEBAR_BG, FONT_FAMILY, FONT_FAMILY_MONO,
)
from core import (
    OLLAMA_DEFAULT_MODEL, OLLAMA_DOWNLOAD_URL,
    get_ollama_status, ollama_install_command,
    ollama_pull_command, ollama_start_command,
)
from ui_theme import apply_modern_theme
from ui_widgets import MainThreadDispatcher

if TYPE_CHECKING:
    from app import CurlRunnerApp


class OllamaSetupWindow(tk.Toplevel):
    """Small setup wizard for Ollama local AI."""

    def __init__(
        self,
        parent: "CurlRunnerApp",
        base_url: str,
        preferred_model: str = "",
        initial_status: dict[str, Any] | None = None,
        on_ready: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._ui = MainThreadDispatcher(self)   # worker thread → main thread
        self.parent_app = parent
        self.base_url = base_url
        self.preferred_model = preferred_model or OLLAMA_DEFAULT_MODEL
        self.status = initial_status or {}
        self.on_ready = on_ready
        self.busy = False

        self.title("Setup Ollama Local AI")
        self.geometry("680x560")
        self.minsize(600, 480)
        self.configure(bg=BG)
        apply_modern_theme(self)
        self.transient(parent)

        self._setup_fonts()
        self._build_ui()
        if self.status:
            self._render_status(self.status)
        self.after(250, self.refresh_status)

    def _setup_fonts(self) -> None:
        self.fn_title = tkfont.Font(family=FONT_FAMILY, size=13, weight="bold")
        self.fn_label = tkfont.Font(family=FONT_FAMILY, size=9)
        self.fn_btn = tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")
        self.fn_small = tkfont.Font(family=FONT_FAMILY, size=8)
        self.fn_mono = tkfont.Font(family=FONT_FAMILY_MONO, size=9)

    def _build_ui(self) -> None:
        hdr = tk.Frame(self, bg=TITLEBAR_BG, height=58)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Setup Ollama Local AI", font=self.fn_title,
                 bg=TITLEBAR_BG, fg=TEXT).pack(anchor="w", padx=16, pady=(10, 0))
        tk.Label(hdr, text="Dùng cho option Free Local khi bấm AI Analyze",
                 font=self.fn_small, bg=TITLEBAR_BG, fg=TEXT_DIM).pack(anchor="w", padx=16)

        body = tk.Frame(self, bg=BG, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        card = tk.Frame(body, bg=BG2, highlightbackground=BORDER,
                        highlightthickness=1, padx=12, pady=10)
        card.pack(fill="x")
        self.status_lbl = tk.Label(card, text="Đang kiểm tra Ollama...",
                                   font=self.fn_btn, bg=BG2, fg=TEXT, anchor="w")
        self.status_lbl.pack(fill="x")
        self.detail_lbl = tk.Label(card, text="", font=self.fn_label,
                                   bg=BG2, fg=TEXT_DIM, anchor="w", justify="left")
        self.detail_lbl.pack(fill="x", pady=(6, 0))

        steps = tk.Frame(body, bg=BG)
        steps.pack(fill="x", pady=(12, 8))
        self.install_btn = self._mkbtn(steps, "Install Ollama", self.install_ollama)
        self.start_btn = self._mkbtn(steps, "Start Ollama", self.start_ollama, pad=(8, 0))
        self.pull_btn = self._mkbtn(steps, f"Pull {self.preferred_model}", self.pull_model, pad=(8, 0))
        self.refresh_btn = self._mkbtn(steps, "Re-check", self.refresh_status, side="right")

        log_frame = tk.Frame(body, bg=BORDER)
        log_frame.pack(fill="both", expand=True)
        self.log_tw = tk.Text(
            log_frame, bg=BG2, fg=TEXT, font=self.fn_mono,
            wrap="word", relief="flat", padx=10, pady=8,
            insertbackground=ACCENT, selectbackground=ACCENT,
            selectforeground=ACTIVE_TEXT, state="disabled", bd=0,
        )
        sb = tk.Scrollbar(log_frame, command=self.log_tw.yview,
                          bg=BG3, troughcolor=BG2, bd=0)
        self.log_tw.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_tw.pack(fill="both", expand=True, padx=1, pady=1)
        self.log_tw.tag_configure("ok", foreground=GREEN)
        self.log_tw.tag_configure("err", foreground=RED_C)
        self.log_tw.tag_configure("dim", foreground=TEXT_DIM)

        foot = tk.Frame(self, bg=BG2, padx=14, pady=10)
        foot.pack(fill="x", side="bottom")
        self._mkbtn(foot, "Open Download Page", lambda: webbrowser.open(OLLAMA_DOWNLOAD_URL))
        self.analyze_btn = self._mkbtn(foot, "Analyze now", self._finish_ready, side="right", pad=(8, 0))
        self._mkbtn(foot, "Close", self.destroy, side="right")

        self._log("Nếu Free Local chưa sẵn sàng, chạy lần lượt: Install -> Start -> Pull model.", "dim")

    def _mkbtn(self, parent: tk.Widget, text: str, cmd,
               side: str = "left", pad: tuple[int, int] = (0, 0)) -> tk.Button:
        b = tk.Button(parent, text=text, font=self.fn_label,
                      bg=BG3, fg=TEXT, activebackground=SURFACE_HOVER,
                      activeforeground=TEXT, relief="flat", cursor="hand2",
                      padx=11, pady=5, command=cmd, bd=0)
        b.bind("<Enter>", lambda _e: b.config(bg=SURFACE_HOVER) if str(b["state"]) == "normal" else None)
        b.bind("<Leave>", lambda _e: b.config(bg=BG3) if str(b["state"]) == "normal" else None)
        b.pack(side=side, padx=pad)
        return b

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for btn in (self.install_btn, self.start_btn, self.pull_btn, self.refresh_btn):
            btn.config(state="disabled" if busy else "normal")
        self._update_buttons()

    def _log(self, text: str, tag: str = "dim") -> None:
        self.log_tw.config(state="normal")
        self.log_tw.insert("end", f"{text}\n", tag)
        self.log_tw.see("end")
        self.log_tw.config(state="disabled")

    def _after_log(self, text: str, tag: str = "dim") -> None:
        self._ui.post(self._log, text, tag)

    def refresh_status(self) -> None:
        if self.busy:
            return

        def worker() -> None:
            status = get_ollama_status(self.preferred_model, self.base_url)
            self._ui.post(self._render_status, status)

        threading.Thread(target=worker, daemon=True).start()

    def _render_status(self, status: dict[str, Any]) -> None:
        was_ready = bool(self.status.get("ready"))
        self.status = status
        ready = bool(status.get("ready"))
        color = GREEN if ready else (YELLOW_C if status.get("installed") else RED_C)
        self.status_lbl.config(text=status.get("message", "Ollama chưa sẵn sàng."), fg=color)
        models = ", ".join(status.get("models", [])[:6]) or "(chưa có model)"
        detail = (
            f"Base URL: {status.get('base_url', self.base_url)}\n"
            f"Ollama CLI: {status.get('cli_path') or '(chưa tìm thấy)'}\n"
            f"Server: {'running' if status.get('api_running') else 'not running'}\n"
            f"Model: {status.get('selected_model') or status.get('target_model') or self.preferred_model}\n"
            f"Installed models: {models}"
        )
        if status.get("api_error") and not status.get("api_running"):
            detail += f"\nAPI detail: {status.get('api_error')}"
        self.detail_lbl.config(text=detail)
        self._update_buttons()

        if ready and not was_ready:
            self._log(f"Ready: {status.get('selected_model')}", "ok")

    def _update_buttons(self) -> None:
        if self.busy:
            return
        status = self.status or {}
        local_endpoint = bool(status.get("local_endpoint", True))
        installed = bool(status.get("cli_path"))
        running = bool(status.get("api_running"))
        ready = bool(status.get("ready"))
        self.install_btn.config(state="normal" if local_endpoint and not installed else "disabled")
        self.start_btn.config(state="normal" if local_endpoint and installed and not running else "disabled")
        self.pull_btn.config(state="normal" if installed and running and not ready else "disabled")
        self.analyze_btn.config(state="normal" if ready else "disabled")

    def install_ollama(self) -> None:
        cmd = ollama_install_command()
        msg = (
            "App sẽ chạy lệnh cài Ollama chính thức:\n\n"
            f"{' '.join(cmd)}\n\n"
            "Tiếp tục cài đặt?"
        )
        if not messagebox.askyesno("Install Ollama", msg, parent=self):
            return
        self._run_command(cmd, "Installing Ollama")

    def start_ollama(self) -> None:
        try:
            cmd = ollama_start_command()
        except Exception as exc:
            self._log(str(exc), "err")
            self.refresh_status()
            return
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
            )
            self._log("Đang start Ollama server...", "dim")
            self.after(1500, self.refresh_status)
            self.after(3500, self.refresh_status)
        except Exception as exc:
            self._log(f"Start failed: {exc}", "err")
            self.refresh_status()

    def pull_model(self) -> None:
        model = self.preferred_model or OLLAMA_DEFAULT_MODEL
        try:
            cmd = ollama_pull_command(model)
        except Exception as exc:
            self._log(str(exc), "err")
            self.refresh_status()
            return
        self._run_command(cmd, f"Pulling model {model}")

    def _run_command(self, cmd: list[str], title: str) -> None:
        self._set_busy(True)
        self._log(f"{title}: {' '.join(cmd)}", "dim")

        def worker() -> None:
            try:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=flags,
                )
                if proc.stdout:
                    for line in proc.stdout:
                        line = line.rstrip("\r\n")
                        if line:
                            self._after_log(line, "dim")
                code = proc.wait()
                if code == 0:
                    self._after_log(f"{title} complete.", "ok")
                else:
                    self._after_log(f"{title} failed with exit code {code}.", "err")
            except Exception as exc:
                self._after_log(f"{title} failed: {exc}", "err")
            finally:
                self._ui.post(self._set_busy, False)
                self._ui.post(lambda: self.after(900, self.refresh_status))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_ready(self) -> None:
        if not self.status.get("ready"):
            self.refresh_status()
            return
        if self.on_ready:
            self.on_ready()
        self.destroy()
