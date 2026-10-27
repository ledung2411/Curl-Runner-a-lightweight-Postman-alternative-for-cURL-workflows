# app.py — CurlRunnerApp: main application window
# Orchestrates all UI panels and business logic

from __future__ import annotations

import re
import uuid
import json
import os
import shlex
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, font as tkfont

from constants import (
    BG, BG2, BG3, SIDEBAR, BORDER,
    CODE_BG,
    ACCENT, ACCENT2, TEXT, TEXT_DIM, TEXT_URL,
    ACTIVE_TEXT, STATUS_TEXT,
    GREEN, RED_C, YELLOW_C, CYAN_C, MAG_C, TAB_BG,
    SURFACE_HOVER, SURFACE_ACTIVE, TITLEBAR_BG,
    FONT_FAMILY, FONT_FAMILY_MONO,
    METHOD_COLORS, status_color,
)
from models import RequestTab
from core import (
    apply_env, run_pre_script, has_executable_code,
    parse_curl, execute_request, DEFAULT_TIMEOUT,
    decode_response, beautify_curl_body,
    build_ai_response_context, analyze_response_with_ai,
    analyze_response_with_ollama, get_ollama_status,
    OLLAMA_DEFAULT_BASE_URL,
)
import store
from importers import import_path, merge_import
from redaction import (
    MASK, REDACTED, is_secret_name, mask_value, redact_curl, redact_url,
    replace_secret_values, secret_map,
)
from scenario_engine import evaluate_assertions, extract_values, join_test_rules, split_test_rules
from ui_compare import CurlCompareWindow
from ui_converter import ConverterWindow
from ui_ollama_setup import OllamaSetupWindow
from ui_scenario import ScenarioWindow
from ui_theme import apply_modern_theme
from ui_widgets import MainThreadDispatcher


class CurlRunnerApp(tk.Tk):
    RESPONSE_PREVIEW_LIMIT = 4_000_000
    JSON_PRETTY_LIMIT = 1_500_000
    JSON_HIGHLIGHT_LIMIT = 250_000
    SEARCH_HIGHLIGHT_LIMIT = 1000

    def __init__(self):
        super().__init__()
        self.title("Curl Runner")
        self.geometry("1400x880")
        self.minsize(980, 660)
        self.configure(bg=BG)
        self.ui_theme_name = apply_modern_theme(self)
        self._ui = MainThreadDispatcher(self)   # worker thread → main thread

        self.settings     = store.load_settings()
        self.history      = store.load_history()
        self.collections  = store.load_collections()
        self.environments = store.load_environments()
        self.active_env   = list(self.environments.keys())[0]

        # Multi-tab state
        self.tabs: list[RequestTab] = []
        self.active_tab_idx = -1

        # Response panel widgets — khai báo tường minh để Pylance nhận diện
        # (thực tế được tạo trong _mk_text_tab qua setattr)
        self.body_tw:     tk.Text  = None  # type: ignore
        self.headers_tw:  tk.Text  = None  # type: ignore
        self.info_tw:     tk.Text  = None  # type: ignore
        self.log_tw:      tk.Text  = None  # type: ignore
        self.ai_tw:       tk.Text  = None  # type: ignore
        self.tests_tw:    tk.Text  = None  # type: ignore
        self.body_frame:    tk.Frame = None  # type: ignore
        self.headers_frame: tk.Frame = None  # type: ignore
        self.info_frame:    tk.Frame = None  # type: ignore
        self.log_frame:     tk.Frame = None  # type: ignore
        self.ai_frame:      tk.Frame = None  # type: ignore
        self.tests_frame:   tk.Frame = None  # type: ignore
        self.stab_history:     tk.Button = None  # type: ignore
        self.stab_collections: tk.Button = None  # type: ignore
        self.rtab_body:    tk.Button = None  # type: ignore
        self.rtab_headers: tk.Button = None  # type: ignore
        self.rtab_info:    tk.Button = None  # type: ignore
        self.rtab_log:     tk.Button = None  # type: ignore
        self.rtab_ai:      tk.Button = None  # type: ignore
        self.rtab_tests:   tk.Button = None  # type: ignore
        self.ai_analyze_btn: tk.Button = None  # type: ignore
        self.ai_status_lbl: tk.Label = None  # type: ignore
        self.ollama_setup_win: tk.Toplevel = None  # type: ignore
        self.openai_api_key = ""
        default_ai_provider = os.environ.get("AI_PROVIDER", "ollama").strip().lower()
        if default_ai_provider not in ("ollama", "openai"):
            default_ai_provider = "ollama"
        self.ai_provider_var = tk.StringVar(value=default_ai_provider)
        self.active_resp_tab = "body"
        self.resp_search_var: tk.StringVar = None  # type: ignore
        self.resp_case_var: tk.BooleanVar = None  # type: ignore
        self.resp_search_entry: tk.Entry = None  # type: ignore
        self.resp_search_count_lbl: tk.Label = None  # type: ignore
        self.response_search_after: str | None = None
        self.response_matches: list[tuple[str, str]] = []
        self.response_match_index = -1
        self.response_match_overflow = False

        self._setup_fonts()
        self._build_ui()
        self._load_font_settings()   # Restore saved font settings
        self._new_tab()   # Start with 1 blank tab
        self._refresh_history_list()
        self._refresh_collection_tree()
        self._refresh_env_selector()
        self.after(600, self._refresh_ollama_status_async)

    # ── FONTS ─────────────────────────────────
    def _setup_fonts(self):
        # Windows 11 Fluent Design typography
        # Primary: Segoe UI Variable (Win11), fallback Segoe UI
        # Mono:    Cascadia Code (Win11 Terminal), fallback Consolas
        self.fn_mono  = tkfont.Font(family=FONT_FAMILY_MONO, size=10)
        self.fn_monos = tkfont.Font(family=FONT_FAMILY_MONO, size=9)
        self.fn_title = tkfont.Font(family=FONT_FAMILY, size=14, weight="bold")
        self.fn_label = tkfont.Font(family=FONT_FAMILY, size=9)
        self.fn_btn   = tkfont.Font(family=FONT_FAMILY, size=9,  weight="bold")
        self.fn_stat  = tkfont.Font(family=FONT_FAMILY, size=12, weight="bold")
        self.fn_badge = tkfont.Font(family=FONT_FAMILY, size=8,  weight="bold")
        self.fn_small = tkfont.Font(family=FONT_FAMILY, size=8)
        self.fn_tab   = tkfont.Font(family=FONT_FAMILY, size=9)

    # ── TOP BAR ───────────────────────────────
    def _build_ui(self):
        topbar = tk.Frame(self, bg=TITLEBAR_BG, height=56)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)
        brand = tk.Frame(topbar, bg=TITLEBAR_BG)
        brand.pack(side="left", padx=18, pady=8)
        tk.Label(brand, text="Curl Runner", font=self.fn_title,
                 bg=TITLEBAR_BG, fg=TEXT).pack(anchor="w")
        theme_label = "ttkbootstrap UI" if self.ui_theme_name.startswith("ttkbootstrap") else "clean UI"
        tk.Label(brand, text=f"API client · scenarios · AI analysis · {theme_label}",
                 font=self.fn_small, bg=TITLEBAR_BG, fg=TEXT_DIM).pack(anchor="w")

        ef = tk.Frame(topbar, bg=TITLEBAR_BG)
        ef.pack(side="right", padx=16)
        tk.Label(ef, text="ENV:", font=self.fn_badge, bg=TITLEBAR_BG, fg=TEXT_DIM).pack(side="left")
        self.env_var = tk.StringVar(value=self.active_env)
        self.env_combo = ttk.Combobox(ef, textvariable=self.env_var, width=16,
                                      state="readonly", font=self.fn_label,
                                      style="TCombobox")
        self.env_combo.pack(side="left", padx=4)
        self.env_combo.bind("<<ComboboxSelected>>", self._on_env_change)
        self._mkbtn(ef, "⚙ Manage",  self._open_env_editor,  side="left", pad=(4,0))
        self._mkbtn(ef, "▶ Scenario", self._open_scenario,    side="left", pad=(10,0))
        self._mkbtn(ef, "⇄ Compare", self._open_compare,     side="left", pad=(10,0))
        self._mkbtn(ef, "⇆ Convert", self._open_converter,   side="left", pad=(10,0))
        self._mkbtn(ef, "🔤 Font",   self._open_font_settings, side="left", pad=(10,0))

        # 3-column layout
        outer = tk.PanedWindow(self, orient="horizontal", bg=BG,
                               sashwidth=4, sashrelief="flat", bd=0)
        outer.pack(fill="both", expand=True)
        outer.add(self._build_sidebar(outer), minsize=200, width=240)
        outer.add(self._build_center(outer),  minsize=380, width=560)
        outer.add(self._build_right(outer),   minsize=300)

    # ══ SIDEBAR ═══════════════════════════════
    def _build_sidebar(self, parent):
        frame = tk.Frame(parent, bg=SIDEBAR)
        tab_row = tk.Frame(frame, bg=SIDEBAR)
        tab_row.pack(fill="x")
        for lbl, val in [("📋 History","history"),("🗂 Collections","collections")]:
            btn = tk.Button(tab_row, text=lbl, font=self.fn_small,
                            bg=SURFACE_ACTIVE if val=="history" else SIDEBAR,
                            fg=ACTIVE_TEXT if val=="history" else TEXT_DIM,
                            relief="flat", cursor="hand2", pady=8, bd=0,
                            command=lambda v=val: self._show_sidebar(v))
            btn.pack(side="left", fill="x", expand=True)
            if val == "history":
                self.stab_history = btn
            else:
                self.stab_collections = btn
        self.sidebar_history     = tk.Frame(frame, bg=SIDEBAR)
        self.sidebar_collections = tk.Frame(frame, bg=SIDEBAR)
        self._build_history_panel(self.sidebar_history)
        self._build_collection_panel(self.sidebar_collections)
        self.sidebar_history.pack(fill="both", expand=True)
        return frame

    def _show_sidebar(self, val):
        for v, fr in [("history",self.sidebar_history),
                      ("collections",self.sidebar_collections)]:
            getattr(self, f"stab_{v}").config(
                bg=SURFACE_ACTIVE if v==val else SIDEBAR,
                fg=ACTIVE_TEXT if v==val else TEXT_DIM)
            if v == val: fr.pack(fill="both", expand=True)
            else:        fr.pack_forget()

    # ── History ──
    def _build_history_panel(self, parent):
        sf = tk.Frame(parent, bg=SIDEBAR)
        sf.pack(fill="x", padx=6, pady=(6,2))
        self.hist_search = tk.Entry(sf, bg=BG3, fg=TEXT_DIM,
                                    insertbackground=ACCENT,
                                    font=self.fn_small, relief="flat", bd=0)
        self.hist_search.pack(fill="x", ipady=4, padx=1)
        self.hist_search.insert(0, "🔍 Tìm kiếm...")
        self.hist_search.bind("<FocusIn>",    lambda e: self._hist_focus(True))
        self.hist_search.bind("<FocusOut>",   lambda e: self._hist_focus(False))
        self.hist_search.bind("<KeyRelease>", lambda e: self._refresh_history_list())

        lf = tk.Frame(parent, bg=SIDEBAR)
        lf.pack(fill="both", expand=True, padx=6, pady=2)
        sb = tk.Scrollbar(lf, bg=BG3, troughcolor=SIDEBAR, bd=0)
        sb.pack(side="right", fill="y")
        self.hist_list = tk.Listbox(lf, bg=BG2, fg=TEXT, font=self.fn_small,
                                    selectbackground=ACCENT, selectforeground=ACTIVE_TEXT,
                                    relief="flat", bd=0, activestyle="none",
                                    yscrollcommand=sb.set)
        self.hist_list.pack(fill="both", expand=True)
        sb.config(command=self.hist_list.yview)
        self.hist_list.bind("<Double-Button-1>", self._load_from_history)
        self.hist_list.bind("<Button-3>",        self._history_ctx)

        bf = tk.Frame(parent, bg=SIDEBAR)
        bf.pack(fill="x", padx=6, pady=(2,6))
        self._mkbtn(bf, "Xóa hết", self._clear_history)
        self.redact_history_var = tk.BooleanVar(value=bool(self.settings.get("redact_history", True)))
        self.history_privacy_btn = self._mkbtn(bf, "🔒", self._show_history_privacy_menu, pad=(6,0))

    def _show_history_privacy_menu(self):
        m = tk.Menu(self, tearoff=0, bg=BG3, fg=TEXT, activebackground=ACCENT)
        m.add_checkbutton(label="Che token/mật khẩu khi lưu lịch sử",
                          variable=self.redact_history_var,
                          command=self._toggle_redact_history)
        m.add_command(label="Che bí mật trong toàn bộ lịch sử hiện có",
                      command=self._redact_existing_history)
        m.tk_popup(self.history_privacy_btn.winfo_rootx(),
                   self.history_privacy_btn.winfo_rooty() + self.history_privacy_btn.winfo_height())

    def _toggle_redact_history(self):
        self.settings["redact_history"] = bool(self.redact_history_var.get())
        store.save_settings(self.settings)

    def _current_secret_map(self, env: dict | None = None) -> dict[str, str]:
        """Biến bí mật (theo tên hoặc do người dùng đánh dấu) của environment đang chọn + biến runtime."""
        values = dict(self.environments.get(self.active_env, {}))
        values.update(env or {})
        return secret_map(values, set(self.settings.get("secret_vars", [])))

    def _redact_existing_history(self):
        if not messagebox.askyesno(
                "Che bí mật trong lịch sử",
                "Thay token/mật khẩu trong toàn bộ lịch sử bằng {{biến}} hoặc [REDACTED]?\n"
                "Không thể hoàn tác."):
            return
        secrets: dict[str, str] = {}
        for values in self.environments.values():
            secrets.update(secret_map(values, set(self.settings.get("secret_vars", []))))
        changed = 0
        for item in self.history:
            curl, url = item.get("curl", ""), item.get("url", "")
            new_curl, new_url = redact_curl(curl, secrets), redact_url(url, secrets)
            if (new_curl, new_url) != (curl, url):
                item["curl"], item["url"] = new_curl, new_url
                changed += 1
        store.save_history(self.history)
        self._refresh_history_list()
        messagebox.showinfo("Che bí mật trong lịch sử", f"Đã che {changed} mục.")

    def _hist_focus(self, on):
        ph = "🔍 Tìm kiếm..."
        if on and self.hist_search.get() == ph:
            self.hist_search.delete(0,"end"); self.hist_search.config(fg=TEXT)
        elif not on and not self.hist_search.get():
            self.hist_search.insert(0, ph); self.hist_search.config(fg=TEXT_DIM)

    def _refresh_history_list(self, *_):
        q = self.hist_search.get().lower()
        if q == "🔍 tìm kiếm...": q = ""
        self.hist_list.delete(0,"end")
        for item in reversed(self.history[-300:]):
            method = item.get("method","?")
            url    = item.get("url","")
            sc     = str(item.get("status",""))
            if q and q not in f"{method} {url}".lower() and q not in sc: continue
            self.hist_list.insert("end", f"  {method:5} {url[:30]}")
            col = status_color(int(sc)) if sc.isdigit() else TEXT_DIM
            self.hist_list.itemconfig(self.hist_list.size()-1, fg=col)

    def _get_visible_history(self):
        q = self.hist_search.get().lower()
        if q == "🔍 tìm kiếm...": q = ""
        out = []
        for item in reversed(self.history[-300:]):
            method = item.get("method","?"); url = item.get("url","")
            sc     = str(item.get("status",""))
            if q and q not in f"{method} {url}".lower() and q not in sc: continue
            out.append(item)
        return out

    def _load_from_history(self, _=None):
        sel = self.hist_list.curselection()
        if not sel: return
        visible = self._get_visible_history()
        if sel[0] < len(visible):
            self._set_curl(visible[sel[0]].get("curl",""))

    def _history_ctx(self, event):
        idx = self.hist_list.nearest(event.y)
        self.hist_list.selection_clear(0,"end")
        self.hist_list.selection_set(idx)
        visible = self._get_visible_history()
        m = tk.Menu(self, tearoff=0, bg=BG3, fg=TEXT, activebackground=ACCENT)
        m.add_command(label="▶  Load vào tab hiện tại", command=self._load_from_history)
        m.add_command(label="➕ Mở trong tab mới",
                      command=lambda: self._load_history_new_tab(idx, visible))
        m.add_command(label="📁 Lưu vào Collection",
                      command=lambda: self._save_to_coll_dialog(
                          visible[idx].get("curl","") if idx < len(visible) else ""))
        m.add_separator()
        m.add_command(label="🗑 Xóa",
                      command=lambda: self._del_hist_item(idx, visible))
        m.tk_popup(event.x_root, event.y_root)

    def _load_history_new_tab(self, idx, visible):
        if idx < len(visible):
            curl = visible[idx].get("curl","")
            self._new_tab(curl=curl)

    def _del_hist_item(self, idx, visible):
        if idx >= len(visible): return
        tid = visible[idx].get("id")
        self.history = [h for h in self.history if h.get("id") != tid]
        store.save_history(self.history)
        self._refresh_history_list()

    def _clear_history(self):
        if messagebox.askyesno("Xác nhận","Xóa toàn bộ lịch sử?"):
            self.history = []
            store.save_history(self.history)
            self._refresh_history_list()

    # ── Collections ──
    def _build_collection_panel(self, parent):
        bf = tk.Frame(parent, bg=SIDEBAR)
        bf.pack(fill="x", padx=6, pady=(6,2))
        self._mkbtn(bf, "＋ New Collection", self._new_collection)
        self.import_btn = self._mkbtn(bf, "⇪ Import", self._show_import_menu, pad=(6,0))

        tf = tk.Frame(parent, bg=SIDEBAR)
        tf.pack(fill="both", expand=True, padx=6, pady=2)
        sb = tk.Scrollbar(tf, bg=BG3, troughcolor=SIDEBAR, bd=0)
        sb.pack(side="right", fill="y")
        self.coll_tree = ttk.Treeview(tf, show="tree", selectmode="browse",
                                      yscrollcommand=sb.set)
        sb.config(command=self.coll_tree.yview)
        style = ttk.Style()
        style.configure("Treeview", background=BG2, foreground=TEXT,
                        fieldbackground=BG2, font=(FONT_FAMILY, 9),
                        rowheight=30, borderwidth=0)
        style.map("Treeview", background=[("selected", SURFACE_ACTIVE)],
                  foreground=[("selected", ACTIVE_TEXT)])
        self.coll_tree.pack(fill="both", expand=True)
        self.coll_tree.bind("<Double-Button-1>", self._load_from_collection)
        self.coll_tree.bind("<Button-3>",        self._coll_ctx)

    def _show_import_menu(self):
        m = tk.Menu(self, tearoff=0, bg=BG3, fg=TEXT, activebackground=ACCENT)
        m.add_command(label="Postman collection / environment, HAR (file)...",
                      command=self._import_file_dialog)
        m.add_command(label="Bruno collection (thư mục)...",
                      command=self._import_folder_dialog)
        m.tk_popup(self.import_btn.winfo_rootx(),
                   self.import_btn.winfo_rooty() + self.import_btn.winfo_height())

    def _import_file_dialog(self):
        path = filedialog.askopenfilename(
            parent=self, title="Import Postman / HAR / Bruno",
            filetypes=[("Postman / HAR", "*.json *.har"), ("Bruno request", "*.bru"), ("All", "*.*")])
        if path:
            self._import_from_path(path)

    def _import_folder_dialog(self):
        path = filedialog.askdirectory(parent=self, title="Chọn thư mục Bruno collection")
        if path:
            self._import_from_path(path)

    def _import_from_path(self, path: str):
        try:
            result = import_path(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Import", str(exc), parent=self)
            return
        created = merge_import(result, self.collections, self.environments)
        store.save_collections(self.collections)
        if result.environments:
            store.save_environments(self.environments)
            self._refresh_env_selector()
        self._refresh_collection_tree()
        self._show_sidebar("collections")
        lines = [f"Nguồn: {result.source} · {result.request_count} request", ""]
        lines += [f"+ {line}" for line in created]
        if result.notes:
            lines += ["", "Lưu ý:"] + [f"• {note}" for note in result.notes[:12]]
            if len(result.notes) > 12:
                lines.append(f"• ... và {len(result.notes) - 12} lưu ý khác")
        messagebox.showinfo("Import xong", "\n".join(lines), parent=self)

    def _refresh_collection_tree(self):
        self.coll_tree.delete(*self.coll_tree.get_children())
        for col_name, items in self.collections.items():
            node = self.coll_tree.insert("","end",
                                         text=f"📁 {col_name} ({len(items)})",
                                         open=True, tags=("col",))
            for it in items:
                self.coll_tree.insert(node,"end",
                                      text=f"  {it.get('method','GET'):5} {it.get('name','')}",
                                      values=(col_name, it["id"]), tags=("item",))
        self.coll_tree.tag_configure("col",  foreground=YELLOW_C)
        self.coll_tree.tag_configure("item", foreground=TEXT)

    def _load_from_collection(self, _=None):
        sel = self.coll_tree.selection()
        if not sel: return
        vals = self.coll_tree.item(sel[0],"values")
        if not vals or len(vals) < 2: return
        col_name, item_id = vals[0], vals[1]
        for it in self.collections.get(col_name,[]):
            if it["id"] == item_id:
                self._set_curl(it["curl"], tests=self._item_tests(it)); return

    def _coll_ctx(self, event):
        iid = self.coll_tree.identify_row(event.y)
        if not iid: return
        self.coll_tree.selection_set(iid)
        vals = self.coll_tree.item(iid,"values")
        m = tk.Menu(self, tearoff=0, bg=BG3, fg=TEXT, activebackground=ACCENT)
        if vals and len(vals) >= 2:
            col_name, item_id = vals[0], vals[1]
            m.add_command(label="▶  Load vào tab hiện tại",
                          command=self._load_from_collection)
            m.add_command(label="➕ Mở trong tab mới",
                          command=lambda: self._open_coll_item_new_tab(col_name, item_id))
            m.add_separator()
            m.add_command(label="✏  Đổi tên",
                          command=lambda: self._rename_coll_item(col_name, item_id))
            m.add_command(label="🗑 Xóa",
                          command=lambda: self._del_coll_item(col_name, item_id))
        else:
            col_name = self.coll_tree.item(iid,"text").split(" (")[0].replace("📁 ","")
            m.add_command(label="🗑 Xóa Collection",
                          command=lambda: self._del_collection(col_name))
        m.tk_popup(event.x_root, event.y_root)

    def _open_coll_item_new_tab(self, col_name, item_id):
        for it in self.collections.get(col_name,[]):
            if it["id"] == item_id:
                self._new_tab(curl=it["curl"], name=it.get("name"), tests=self._item_tests(it))
                return

    def _new_collection(self):
        name = simpledialog.askstring("Tên Collection","Nhập tên mới:", parent=self)
        if name and name.strip():
            self.collections.setdefault(name.strip(),[])
            store.save_collections(self.collections)
            self._refresh_collection_tree()

    def _item_tests(self, item: dict) -> str:
        return join_test_rules(item.get("extractors", ""), item.get("assertions", ""))

    def _save_to_coll_dialog(self, curl_str, tests: str = ""):
        if not curl_str: return
        if not self.collections:
            if messagebox.askyesno("Chưa có Collection","Tạo mới?"):
                self._new_collection()
            if not self.collections: return
        win = tk.Toplevel(self)
        win.title("Lưu vào Collection")
        win.configure(bg=BG); win.geometry("360x210"); win.grab_set()
        tk.Label(win, text="Collection:", font=self.fn_label,
                 bg=BG, fg=TEXT_DIM).pack(pady=(16,2))
        col_var = tk.StringVar(value=list(self.collections.keys())[0])
        ttk.Combobox(win, textvariable=col_var,
                     values=list(self.collections.keys()),
                     state="readonly", font=self.fn_label).pack(padx=20, fill="x")
        tk.Label(win, text="Tên request:", font=self.fn_label,
                 bg=BG, fg=TEXT_DIM).pack(pady=(10,2))
        name_e = tk.Entry(win, font=self.fn_label, bg=BG3, fg=TEXT,
                          insertbackground=ACCENT, relief="flat")
        name_e.pack(padx=20, fill="x"); name_e.insert(0,"New Request")
        def do_save():
            col  = col_var.get()
            name = name_e.get().strip() or "New Request"
            try:    method = parse_curl(curl_str).get("method","GET")
            except: method = "GET"
            item = {
                "id": str(uuid.uuid4())[:8], "name": name,
                "method": method, "curl": curl_str
            }
            extractors, assertions = split_test_rules(tests)
            if extractors: item["extractors"] = extractors
            if assertions: item["assertions"] = assertions
            self.collections[col].append(item)
            store.save_collections(self.collections)
            self._refresh_collection_tree()
            win.destroy()
        tk.Button(win, text="💾 Lưu", font=self.fn_btn, bg=ACCENT, fg=ACTIVE_TEXT,
                  relief="flat", command=do_save, pady=6).pack(pady=14)

    def _rename_coll_item(self, col_name, item_id):
        for it in self.collections.get(col_name,[]):
            if it["id"] == item_id:
                new = simpledialog.askstring("Đổi tên","Tên mới:",
                                             initialvalue=it["name"], parent=self)
                if new:
                    it["name"] = new.strip()
                    store.save_collections(self.collections)
                    self._refresh_collection_tree()
                return

    def _del_coll_item(self, col_name, item_id):
        self.collections[col_name] = [i for i in self.collections.get(col_name,[])
                                       if i["id"] != item_id]
        store.save_collections(self.collections); self._refresh_collection_tree()

    def _del_collection(self, col_name):
        if messagebox.askyesno("Xác nhận", f"Xóa '{col_name}'?"):
            self.collections.pop(col_name, None)
            store.save_collections(self.collections); self._refresh_collection_tree()

    # ══ ENVIRONMENT ═══════════════════════════
    def _refresh_env_selector(self):
        names = list(self.environments.keys())
        self.env_combo["values"] = names
        if self.active_env not in names:
            self.active_env = names[0] if names else "Default"
        self.env_var.set(self.active_env)

    def _on_env_change(self, _=None):
        self.active_env = self.env_var.get()
        self._update_env_hint()

    def _open_env_editor(self):
        # Chỉnh sửa trên bản nháp; chỉ áp dụng khi bấm "Lưu & Đóng".
        draft = {name: dict(values) for name, values in self.environments.items()}
        secret_names = set(self.settings.get("secret_vars", []))
        win = tk.Toplevel(self)
        win.title("Environment Manager")
        win.configure(bg=BG); win.geometry("700x500"); win.grab_set()

        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=12, pady=(10,4))
        tk.Label(top, text="Environment:", font=self.fn_label,
                 bg=BG, fg=TEXT_DIM).pack(side="left")
        env_sel = tk.StringVar(value=self.active_env)
        env_cb  = ttk.Combobox(top, textvariable=env_sel,
                                values=list(draft.keys()),
                                state="readonly", font=self.fn_label, width=18)
        env_cb.pack(side="left", padx=6)

        # Environment đang hiển thị trong bảng; dùng để không mất các chỉnh sửa
        # chưa lưu khi người dùng chuyển sang environment khác.
        editing = {"name": env_sel.get()}
        # Giá trị thật của từng dòng (bảng chỉ hiển thị •••••• cho biến bí mật).
        real: dict[str, str] = {}
        revealed = {"on": False}

        def secret_label(name: str) -> str:
            if name in secret_names:
                return "🔒"
            return "🔒 auto" if is_secret_name(name) else ""

        def show_row(iid: str, name: str) -> None:
            value = real.get(iid, "")
            shown = value if revealed["on"] else mask_value(name, value, secret_names)
            tree.item(iid, values=(name, shown, secret_label(name)))

        def row_name(iid: str) -> str:
            return str(tree.item(iid, "values")[0])

        def insert_row(name: str, value: str) -> None:
            iid = tree.insert("", "end", values=(name, "", ""))
            real[iid] = value
            show_row(iid, name)

        def commit_tree():
            name = editing["name"]
            if name not in draft:
                return
            rows = {}
            for iid in tree.get_children():
                key = row_name(iid).strip()
                if key:
                    rows[key] = real.get(iid, "")
            draft[name] = rows

        def new_env():
            n = simpledialog.askstring("Tên","Tên environment mới:", parent=win)
            if n and n.strip():
                commit_tree()
                draft.setdefault(n.strip(),{})
                env_cb["values"] = list(draft.keys())
                env_sel.set(n.strip()); load_vars()

        def del_env():
            n = env_sel.get()
            if len(draft) <= 1:
                messagebox.showinfo("","Phải giữ ít nhất 1.", parent=win); return
            if messagebox.askyesno("Xác nhận", f"Xóa '{n}'?", parent=win):
                draft.pop(n, None)
                env_cb["values"] = list(draft.keys())
                env_sel.set(list(draft.keys())[0]); load_vars()

        def toggle_reveal():
            revealed["on"] = not revealed["on"]
            reveal_btn.config(text="🙈 Ẩn giá trị" if revealed["on"] else "👁 Hiện giá trị")
            for iid in tree.get_children():
                show_row(iid, row_name(iid))

        self._mkbtn(top, "＋ Mới", new_env, side="left", pad=(4,0))
        self._mkbtn(top, "🗑",     del_env, side="left", pad=(4,0))
        reveal_btn = self._mkbtn(top, "👁 Hiện giá trị", toggle_reveal, side="right")

        tbl = tk.Frame(win, bg=BG2)
        tbl.pack(fill="both", expand=True, padx=12, pady=4)
        cols = ("variable","value","secret")
        tree = ttk.Treeview(tbl, columns=cols, show="headings", height=14)
        tree.heading("variable", text="Variable  ({{tên}})")
        tree.heading("value",    text="Value")
        tree.heading("secret",   text="Bí mật")
        tree.column("variable", width=200); tree.column("value", width=360)
        tree.column("secret", width=80, anchor="center", stretch=False)
        vsb = tk.Scrollbar(tbl, command=tree.yview, bg=BG3, troughcolor=BG2, bd=0)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y"); tree.pack(fill="both", expand=True)

        def load_vars():
            editing["name"] = env_sel.get()
            tree.delete(*tree.get_children())
            real.clear()
            for k, v in draft.get(env_sel.get(),{}).items():
                insert_row(str(k), str(v))

        env_cb.bind("<<ComboboxSelected>>", lambda e: (commit_tree(), load_vars()))
        load_vars()

        def edit_cell(event):
            iid = tree.identify_row(event.y)
            col = tree.identify_column(event.x)
            if not iid: return
            col_idx = int(col[1:])-1
            if col_idx == 2:   # cột Bí mật: bật/tắt đánh dấu thủ công
                name = row_name(iid)
                secret_names.symmetric_difference_update({name})
                show_row(iid, name)
                return
            bbox = tree.bbox(iid, col)
            if not bbox: return
            x,y,w,h = bbox
            val = row_name(iid) if col_idx == 0 else real.get(iid, "")
            ent = tk.Entry(tbl, font=self.fn_label, bg=BG3, fg=TEXT,
                           insertbackground=ACCENT, relief="flat", bd=1)
            ent.place(x=x,y=y,width=w,height=h)
            ent.insert(0,val); ent.focus_set()
            def commit(_=None):
                if not ent.winfo_exists(): return
                if col_idx == 0:
                    show_row(iid, ent.get())
                else:
                    real[iid] = ent.get()
                    show_row(iid, row_name(iid))
                ent.destroy()
            ent.bind("<Return>",   commit)
            ent.bind("<FocusOut>", commit)

        tree.bind("<Double-Button-1>", edit_cell)

        def delete_row():
            for iid in tree.selection():
                real.pop(iid, None)
                tree.delete(iid)

        bf = tk.Frame(win, bg=BG)
        bf.pack(fill="x", padx=12, pady=(4,12))

        def save_close():
            env_name = env_sel.get()
            commit_tree()
            self.environments = draft
            store.save_environments(self.environments)
            self.settings["secret_vars"] = sorted(secret_names)
            store.save_settings(self.settings)
            self._refresh_env_selector()
            self.active_env = env_name
            self.env_var.set(env_name)
            self._update_env_hint()
            win.destroy()

        self._mkbtn(bf, "＋ Thêm dòng", lambda: insert_row("NEW_VAR", "value"), side="left")
        self._mkbtn(bf, "🗑 Xóa dòng", delete_row, side="left", pad=(6,0))
        tk.Label(bf, text="Double-click để sửa · cột Bí mật: đánh dấu biến cần che",
                 font=self.fn_small, bg=BG, fg=TEXT_DIM).pack(side="left", padx=(10,0))
        tk.Button(bf, text="💾 Lưu & Đóng", font=self.fn_btn, bg=ACCENT, fg=ACTIVE_TEXT,
                  relief="flat", command=save_close, pady=5, padx=14).pack(side="right")

    # ══ CENTER (MULTI-TAB INPUT) ══════════════
    def _build_center(self, parent):
        frame = tk.Frame(parent, bg=BG)

        # ── Tab bar
        tab_bar_wrap = tk.Frame(frame, bg=TAB_BG)
        tab_bar_wrap.pack(fill="x", side="top")

        # Scrollable tab bar
        self.tab_canvas = tk.Canvas(tab_bar_wrap, bg=TAB_BG, height=34,
                                    highlightthickness=0, bd=0)
        self.tab_canvas.pack(side="left", fill="x", expand=True)
        self.tab_frame  = tk.Frame(self.tab_canvas, bg=TAB_BG)
        self.tab_canvas.create_window((0,0), window=self.tab_frame, anchor="nw")
        self.tab_frame.bind("<Configure>",
                            lambda e: self.tab_canvas.configure(
                                scrollregion=self.tab_canvas.bbox("all")))

        # New tab button
        tk.Button(tab_bar_wrap, text="＋", font=self.fn_title,
                  bg=TAB_BG, fg=TEXT_DIM, activebackground=BG3,
                  relief="flat", cursor="hand2", padx=10, bd=0,
                  command=self._new_tab).pack(side="right", padx=4)

        # ── Tab content area (swappable)
        self.center_content = tk.Frame(frame, bg=BG)
        self.center_content.pack(fill="both", expand=True)

        return frame

    def _build_tab_content(self, tab: RequestTab) -> tk.Frame:
        """Tạo widget content cho 1 tab."""
        frame = tk.Frame(self.center_content, bg=BG, padx=12, pady=8)

        # Header row
        hdr = tk.Frame(frame, bg=BG)
        hdr.pack(fill="x", pady=(0,4))
        self._sec(hdr, "CURL COMMAND", side="left")
        lbl_env = tk.Label(hdr, text="", font=self.fn_small, bg=BG, fg=TEXT_DIM)
        lbl_env.pack(side="right")
        tab._env_hint_lbl = lbl_env

        # Toolbar
        tb = tk.Frame(frame, bg=BG)
        tb.pack(fill="x", pady=(0,4))
        self._mkbtn(tb, "📂 Import",      lambda t=tab: self._import_file(t),           side="left")
        self._mkbtn(tb, "↘ Parse",       lambda t=tab: self._parse_curl_to_builder(t, switch=True, force=True, show_status=True), side="left", pad=(6,0))
        self._mkbtn(tb, "✨ Beautify",    lambda t=tab: self._beautify_body(t),          side="left", pad=(6,0))
        self._mkbtn(tb, "✂ Xóa",         lambda t=tab: self._clear_input(t),            side="left", pad=(6,0))
        self._mkbtn(tb, "➕ Collection",  lambda t=tab: self._save_tab_to_coll(t),       side="left", pad=(6,0))

        # Notebook: Curl input | Pre-request Script
        nb = ttk.Notebook(frame)
        nb.pack(fill="both", expand=True)

        # ── Request builder tab
        request_frame = tk.Frame(nb, bg=BG2)
        nb.add(request_frame, text="  Request  ")
        tab._request_frame = request_frame

        req_top = tk.Frame(request_frame, bg=BG2)
        req_top.pack(fill="x", padx=8, pady=(8, 6))
        tab._method_var = tk.StringVar(value=tab.builder_method or "GET")
        method_cb = ttk.Combobox(
            req_top, textvariable=tab._method_var,
            values=("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"),
            state="readonly", width=9, font=self.fn_label,
        )
        method_cb.pack(side="left")
        tab._url_var = tk.StringVar(value=tab.builder_url)
        url_entry = tk.Entry(
            req_top, textvariable=tab._url_var,
            font=self.fn_label, bg=BG3, fg=TEXT, insertbackground=ACCENT,
            relief="flat", bd=0,
        )
        url_entry.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=5)

        req_nb = ttk.Notebook(request_frame)
        req_nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        headers_frame = tk.Frame(req_nb, bg=BG2)
        req_nb.add(headers_frame, text="  Headers  ")
        headers_wrap = tk.Frame(headers_frame, bg=BORDER)
        headers_wrap.pack(fill="both", expand=True, padx=1, pady=1)
        headers_tree = ttk.Treeview(
            headers_wrap, columns=("key", "value"), show="headings",
            selectmode="browse", height=7,
        )
        headers_tree.heading("key", text="Header")
        headers_tree.heading("value", text="Value")
        headers_tree.column("key", width=180, anchor="w", stretch=False)
        headers_tree.column("value", width=360, anchor="w", stretch=True)
        headers_sb_y = tk.Scrollbar(headers_wrap, command=headers_tree.yview,
                                    bg=BG3, troughcolor=BG2, bd=0)
        headers_tree.configure(yscrollcommand=headers_sb_y.set)
        headers_sb_y.pack(side="right", fill="y")
        headers_tree.pack(fill="both", expand=True, padx=1, pady=1)
        tab._headers_tree = headers_tree

        header_edit = tk.Frame(headers_frame, bg=BG2)
        header_edit.pack(fill="x", padx=1, pady=(7, 1))
        tab._header_key_var = tk.StringVar()
        tab._header_value_var = tk.StringVar()
        tk.Label(header_edit, text="Header", font=self.fn_small,
                 bg=BG2, fg=TEXT_DIM).pack(side="left", padx=(0, 5))
        key_entry = tk.Entry(
            header_edit, textvariable=tab._header_key_var,
            font=self.fn_label, bg=BG3, fg=TEXT, insertbackground=ACCENT,
            relief="flat", bd=0, width=22,
        )
        key_entry.pack(side="left", ipady=4)
        tk.Label(header_edit, text="Value", font=self.fn_small,
                 bg=BG2, fg=TEXT_DIM).pack(side="left", padx=(10, 5))
        value_entry = tk.Entry(
            header_edit, textvariable=tab._header_value_var,
            font=self.fn_label, bg=BG3, fg=TEXT, insertbackground=ACCENT,
            relief="flat", bd=0,
        )
        value_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._mkbtn(header_edit, "Add/Update", lambda t=tab: self._add_update_header_row(t),
                    side="left", pad=(8, 0))
        self._mkbtn(header_edit, "Delete", lambda t=tab: self._delete_header_row(t),
                    side="left", pad=(6, 0))
        self._mkbtn(header_edit, "Clear", lambda t=tab: self._clear_header_rows(t),
                    side="left", pad=(6, 0))
        headers_tree.bind("<<TreeviewSelect>>", lambda _e, t=tab: self._load_selected_header_row(t))
        key_entry.bind("<Return>", lambda _e, t=tab: self._add_update_header_row(t))
        value_entry.bind("<Return>", lambda _e, t=tab: self._add_update_header_row(t))
        self._set_header_rows(tab, self._parse_headers_text(tab.builder_headers), dirty=False)

        body_frame = tk.Frame(req_nb, bg=BG2)
        req_nb.add(body_frame, text="  Body  ")
        body_wrap = tk.Frame(body_frame, bg=BORDER)
        body_wrap.pack(fill="both", expand=True, padx=1, pady=1)
        body_tw = tk.Text(
            body_wrap, bg=CODE_BG, fg=TEXT, insertbackground=ACCENT,
            font=self.fn_mono, wrap="none", relief="flat",
            padx=10, pady=8, selectbackground=ACCENT,
            selectforeground=ACTIVE_TEXT, undo=True, bd=0,
        )
        body_sb_y = tk.Scrollbar(body_wrap, command=body_tw.yview,
                                 bg=BG3, troughcolor=BG2, bd=0)
        body_sb_x = tk.Scrollbar(body_wrap, orient="horizontal", command=body_tw.xview,
                                 bg=BG3, troughcolor=BG2, bd=0)
        body_tw.configure(yscrollcommand=body_sb_y.set, xscrollcommand=body_sb_x.set)
        body_sb_y.pack(side="right", fill="y")
        body_sb_x.pack(side="bottom", fill="x")
        body_tw.pack(fill="both", expand=True)
        body_tw.insert("1.0", tab.builder_body)
        tab._body_builder_tw = body_tw

        tab._method_var.trace_add("write", lambda *_args, t=tab: self._mark_builder_dirty(t))
        tab._url_var.trace_add("write", lambda *_args, t=tab: self._mark_builder_dirty(t))
        body_tw.bind("<KeyRelease>", lambda _e, t=tab: self._mark_builder_dirty(t))
        body_tw.bind("<<Paste>>", lambda _e, t=tab: self.after(80, lambda: self._mark_builder_dirty(t)))

        # ── Curl tab
        curl_frame = tk.Frame(nb, bg=BG2)
        nb.add(curl_frame, text="  curl  ")

        wrap = tk.Frame(curl_frame, bg=BORDER)
        wrap.pack(fill="both", expand=True, padx=1, pady=1)
        curl_tw = tk.Text(wrap, bg=BG2, fg=TEXT, insertbackground=ACCENT,
                          font=self.fn_mono, wrap="word", relief="flat",
                          padx=10, pady=8, selectbackground=ACCENT,
                          selectforeground=ACTIVE_TEXT, undo=True, bd=0)
        sb_c = tk.Scrollbar(wrap, command=curl_tw.yview, bg=BG3, troughcolor=BG2, bd=0)
        curl_tw.configure(yscrollcommand=sb_c.set)
        sb_c.pack(side="right", fill="y")
        curl_tw.pack(fill="both", expand=True)
        tab._curl_tw = curl_tw

        # Placeholder
        if tab.curl:
            curl_tw.insert("1.0", tab.curl)
        else:
            self._set_ph(curl_tw, tab)
        curl_tw.bind("<FocusIn>",    lambda e, t=tab: self._clear_ph(t))
        curl_tw.bind("<FocusOut>",   lambda e, t=tab: self._restore_ph(t))
        curl_tw.bind("<KeyRelease>", lambda e, t=tab: (self._update_env_hint(t), self._schedule_curl_parse(t)))
        curl_tw.bind("<<Paste>>", lambda e, t=tab: self.after(100, lambda: self._parse_curl_to_builder(t, switch=True, force=True, show_status=True)))

        # ── Pre-request script tab
        pre_frame = tk.Frame(nb, bg=BG2)
        nb.add(pre_frame, text="  ⚡ Pre-request Script  ")

        pre_hdr = tk.Frame(pre_frame, bg=BG2)
        pre_hdr.pack(fill="x", padx=8, pady=(6,2))
        tk.Label(pre_hdr,
                 text="Python script chạy TRƯỚC khi gửi request. Dùng set_env('key','val') để set biến.",
                 font=self.fn_small, bg=BG2, fg=TEXT_DIM).pack(side="left")
        self._mkbtn(pre_hdr, "📋 Ví dụ",
                    lambda t=tab: self._insert_script_example(t),
                    side="right")

        pre_wrap = tk.Frame(pre_frame, bg=BORDER)
        pre_wrap.pack(fill="both", expand=True, padx=8, pady=(2,4))
        pre_tw = tk.Text(pre_wrap, bg=CODE_BG, fg=TEXT, insertbackground=ACCENT,
                         font=self.fn_mono, wrap="none", relief="flat",
                         padx=10, pady=8, selectbackground=ACCENT,
                         selectforeground=ACTIVE_TEXT, undo=True, bd=0,
                         tabs=("28",))
        sb_p = tk.Scrollbar(pre_wrap, command=pre_tw.yview, bg=BG3, troughcolor=BG2, bd=0)
        pre_tw.configure(yscrollcommand=sb_p.set)
        sb_p.pack(side="right", fill="y")
        pre_tw.pack(fill="both", expand=True)
        tab._pre_tw = pre_tw

        if tab.pre_script:
            pre_tw.insert("1.0", tab.pre_script)
        else:
            pre_tw.insert("1.0", "# Viết Python script ở đây\n# Ví dụ: set_env('token', 'abc123')\n")
            pre_tw.config(fg=TEXT_DIM)
        pre_tw.bind("<FocusIn>", lambda e, tw=pre_tw: (
            tw.config(fg=TEXT) if tw.get("1.0","end").strip().startswith("#") else None
        ))

        # ── Tests tab: assertion + lưu biến từ response
        tests_frame = tk.Frame(nb, bg=BG2)
        nb.add(tests_frame, text="  ✅ Tests  ")
        tests_hdr = tk.Frame(tests_frame, bg=BG2)
        tests_hdr.pack(fill="x", padx=8, pady=(6,2))
        tk.Label(tests_hdr,
                 text="Kiểm tra response sau khi gửi. Dòng `ten = json:$.path` lưu giá trị vào environment đang chọn.",
                 font=self.fn_small, bg=BG2, fg=TEXT_DIM).pack(side="left")
        self._mkbtn(tests_hdr, "📋 Ví dụ",
                    lambda t=tab: self._insert_tests_example(t),
                    side="right")
        tests_wrap = tk.Frame(tests_frame, bg=BORDER)
        tests_wrap.pack(fill="both", expand=True, padx=8, pady=(2,4))
        tests_tw = tk.Text(tests_wrap, bg=CODE_BG, fg=TEXT, insertbackground=ACCENT,
                           font=self.fn_mono, wrap="none", relief="flat",
                           padx=10, pady=8, selectbackground=ACCENT,
                           selectforeground=ACTIVE_TEXT, undo=True, bd=0)
        sb_t = tk.Scrollbar(tests_wrap, command=tests_tw.yview, bg=BG3, troughcolor=BG2, bd=0)
        tests_tw.configure(yscrollcommand=sb_t.set)
        sb_t.pack(side="right", fill="y")
        tests_tw.pack(fill="both", expand=True)
        if tab.tests:
            tests_tw.insert("1.0", tab.tests)
        tab._tests_tw = tests_tw

        tab._nb = nb
        if tab.curl:
            self._parse_curl_to_builder(tab, switch=True, force=True, show_status=False)
        elif not tab.builder_dirty:
            nb.select(curl_frame)

        # ── Options
        opt = tk.Frame(frame, bg=BG)
        opt.pack(fill="x", pady=(6,2))
        tab._var_ssl      = tk.BooleanVar(value=True)
        tab._var_redirect = tk.BooleanVar(value=True)
        tab._var_decode   = tk.BooleanVar(value=True)
        self._chk(opt, "Verify SSL",      tab._var_ssl)
        self._chk(opt, "Follow Redirect", tab._var_redirect)
        self._chk(opt, "Auto Decode",     tab._var_decode)
        tk.Label(opt, text="Timeout (s):", font=self.fn_label,
                 bg=BG, fg=TEXT_DIM).pack(side="left", padx=(10,4))
        tab._timeout_var = tk.StringVar(value="30")
        tk.Entry(opt, textvariable=tab._timeout_var, font=self.fn_monos,
                 bg=BG3, fg=TEXT, insertbackground=ACCENT,
                 relief="flat", width=5, bd=0).pack(side="left")
        tk.Label(opt, text="Repeat:", font=self.fn_label,
                 bg=BG, fg=TEXT_DIM).pack(side="left", padx=(10,4))
        tab._repeat_var = tk.StringVar(value="1")
        tk.Entry(opt, textvariable=tab._repeat_var, font=self.fn_monos,
                 bg=BG3, fg=TEXT, insertbackground=ACCENT,
                 relief="flat", width=5, bd=0).pack(side="left")

        # ── Send button
        send_btn = tk.Button(
            frame, text="▶  SEND REQUEST",
            font=self.fn_btn, bg=ACCENT, fg=ACTIVE_TEXT,
            activebackground=ACCENT2, activeforeground=ACTIVE_TEXT,
            relief="flat", cursor="hand2", padx=20, pady=8,
            command=lambda t=tab: self._send(t)
        )
        send_btn.pack(fill="x", pady=(8,2))
        tab._send_btn = send_btn

        status_lbl = tk.Label(frame, text="", font=self.fn_label,
                              bg=BG, fg=TEXT_DIM, anchor="w")
        status_lbl.pack(fill="x")
        tab._status_lbl = status_lbl

        return frame

    # ── Tab bar management ────────────────────
    def _new_tab(self, curl="", name=None, pre_script="", tests=""):
        tab = RequestTab(name=name, curl=curl, pre_script=pre_script, tests=tests)
        self.tabs.append(tab)
        self._render_tab_bar()
        self._switch_tab(len(self.tabs)-1)

    def _render_tab_bar(self):
        for w in self.tab_frame.winfo_children():
            w.destroy()
        for i, tab in enumerate(self.tabs):
            is_active = (i == self.active_tab_idx)
            frm = tk.Frame(self.tab_frame,
                           bg=BG if is_active else TAB_BG,
                           padx=2, pady=0)
            frm.pack(side="left", padx=(0,1))

            # Editable tab name on double-click
            lbl = tk.Label(frm,
                           text=f"  {tab.name[:14]}  ",
                           font=self.fn_tab,
                           bg=BG2 if is_active else TAB_BG,
                           fg=TEXT if is_active else TEXT_DIM,
                           cursor="hand2")
            lbl.pack(side="left")
            lbl.bind("<Button-1>",        lambda e, idx=i: self._switch_tab(idx))
            lbl.bind("<Double-Button-1>", lambda e, idx=i: self._rename_tab(idx))

            # Close button (hide if only 1 tab)
            if len(self.tabs) > 1:
                close = tk.Label(frm, text="✕", font=self.fn_small,
                                 bg=BG if is_active else TAB_BG,
                                 fg=TEXT_DIM, cursor="hand2", padx=2)
                close.pack(side="left")
                close.bind("<Button-1>", lambda e, idx=i: self._close_tab(idx))

            # Bottom border for active tab
            if is_active:
                indicator = tk.Frame(frm, bg=ACCENT, height=3)
                indicator.pack(fill="x", side="bottom")

    def _switch_tab(self, idx):
        # Save current tab's content before switching
        if self.active_tab_idx >= 0 and self.active_tab_idx < len(self.tabs):
            self._save_tab_state(self.tabs[self.active_tab_idx])

        # Hide all content frames
        for w in self.center_content.winfo_children():
            w.pack_forget()

        self.active_tab_idx = idx
        tab = self.tabs[idx]

        # Build content frame if not yet built
        if not hasattr(tab, "_frame") or tab._frame is None:
            tab._frame = self._build_tab_content(tab)

        tab._frame.pack(fill="both", expand=True)
        self._render_tab_bar()
        self._update_env_hint(tab)

        # Restore response panel
        if tab.response is not None:
            self._restore_response(tab)
        else:
            self._clear_response_panel()

    def _save_tab_state(self, tab):
        if not hasattr(tab, "_curl_tw"): return
        curl = tab._curl_tw.get("1.0","end").strip()
        tab.curl = "" if getattr(tab,"_ph_active",False) else curl
        self._save_builder_state(tab)
        tab.builder_dirty = getattr(tab, "_builder_dirty", False)
        if hasattr(tab, "_pre_tw"):
            tab.pre_script = tab._pre_tw.get("1.0","end").strip()
        tab.tests = self._current_tests(tab)

    def _close_tab(self, idx):
        if len(self.tabs) <= 1: return
        self._save_tab_state(self.tabs[idx])
        # Destroy frame
        if hasattr(self.tabs[idx], "_frame") and self.tabs[idx]._frame:
            self.tabs[idx]._frame.destroy()
        self.tabs.pop(idx)
        new_idx = min(idx, len(self.tabs)-1)
        self.active_tab_idx = -1
        self._switch_tab(new_idx)

    def _rename_tab(self, idx):
        tab = self.tabs[idx]
        new = simpledialog.askstring("Đổi tên tab","Tên mới:",
                                     initialvalue=tab.name, parent=self)
        if new and new.strip():
            tab.name = new.strip()
            self._render_tab_bar()

    # ── Placeholder per-tab ───────────────────
    PH = ("Paste hoặc nhập curl command...\n\n"
          "Hỗ trợ biến: curl {{base_url}}/api \\\n"
          "  -H 'Authorization: Bearer {{token}}'\n\n"
          "Ví dụ: curl https://httpbin.org/get")

    def _set_ph(self, tw, tab):
        tw.insert("1.0", self.PH)
        tw.config(fg="#555b70")
        tab._ph_active = True

    def _clear_ph(self, tab):
        if getattr(tab,"_ph_active",False):
            tab._curl_tw.delete("1.0","end")
            tab._curl_tw.config(fg=TEXT)
            tab._ph_active = False

    def _restore_ph(self, tab):
        if not tab._curl_tw.get("1.0","end").strip():
            self._set_ph(tab._curl_tw, tab)

    def _mark_builder_dirty(self, tab) -> None:
        if getattr(tab, "_syncing_builder", False):
            return
        tab._builder_dirty = True
        tab.builder_dirty = True
        self._save_builder_state(tab)
        self._update_env_hint(tab)

    def _save_builder_state(self, tab) -> None:
        if not hasattr(tab, "_method_var") or tab._method_var is None:
            return
        tab.builder_method = tab._method_var.get().strip().upper() or "GET"
        tab.builder_url = tab._url_var.get().strip() if tab._url_var else ""
        tab.builder_headers = self._headers_editor_to_text(tab)
        tab.builder_body = (
            tab._body_builder_tw.get("1.0", "end-1c") if tab._body_builder_tw else ""
        )

    def _parse_headers_text(self, text: str) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for line in (text or "").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if ":" in raw:
                key, _, value = raw.partition(":")
                rows.append((key.strip(), value.strip()))
            else:
                rows.append((raw, ""))
        return [(key, value) for key, value in rows if key]

    def _header_rows_from_tree(self, tab) -> list[tuple[str, str]]:
        tree = getattr(tab, "_headers_tree", None)
        if not tree:
            return self._parse_headers_text(getattr(tab, "builder_headers", ""))
        rows: list[tuple[str, str]] = []
        for item_id in tree.get_children():
            values = tree.item(item_id, "values")
            key = str(values[0]).strip() if values else ""
            value = str(values[1]).strip() if len(values) > 1 else ""
            if key:
                rows.append((key, value))
        return rows

    def _headers_editor_to_text(self, tab) -> str:
        return "\n".join(f"{key}: {value}" for key, value in self._header_rows_from_tree(tab))

    def _set_header_rows(self, tab, rows, dirty: bool = False) -> None:
        tree = getattr(tab, "_headers_tree", None)
        if not tree:
            tab.builder_headers = "\n".join(f"{key}: {value}" for key, value in rows)
            return
        tab._syncing_builder = True
        try:
            tree.delete(*tree.get_children())
            if isinstance(rows, dict):
                iterable = rows.items()
            else:
                iterable = rows or []
            for key, value in iterable:
                key = str(key).strip()
                if key:
                    tree.insert("", "end", values=(key, str(value).strip()))
            if getattr(tab, "_header_key_var", None):
                tab._header_key_var.set("")
            if getattr(tab, "_header_value_var", None):
                tab._header_value_var.set("")
        finally:
            tab._syncing_builder = False
        tab._builder_dirty = dirty
        tab.builder_dirty = dirty
        tab.builder_headers = self._headers_editor_to_text(tab)

    def _load_selected_header_row(self, tab) -> None:
        tree = getattr(tab, "_headers_tree", None)
        if not tree:
            return
        selected = tree.selection()
        if not selected:
            return
        values = tree.item(selected[0], "values")
        tab._header_key_var.set(str(values[0]) if values else "")
        tab._header_value_var.set(str(values[1]) if len(values) > 1 else "")

    def _add_update_header_row(self, tab) -> str:
        tree = getattr(tab, "_headers_tree", None)
        if not tree:
            return "break"
        key = tab._header_key_var.get().strip()
        value = tab._header_value_var.get().strip()
        if not key:
            tab._status_lbl.config(text="Header cần có tên.", fg=RED_C)
            return "break"
        selected = tree.selection()
        target = selected[0] if selected else None
        if target is None:
            for item_id in tree.get_children():
                values = tree.item(item_id, "values")
                if values and str(values[0]).lower() == key.lower():
                    target = item_id
                    break
        if target:
            tree.item(target, values=(key, value))
            tree.selection_set(target)
        else:
            target = tree.insert("", "end", values=(key, value))
            tree.selection_set(target)
            tree.see(target)
        tab._header_key_var.set("")
        tab._header_value_var.set("")
        tab._builder_dirty = True
        tab.builder_dirty = True
        self._save_builder_state(tab)
        self._update_env_hint(tab)
        tab._status_lbl.config(text="Header đã cập nhật.", fg=GREEN)
        return "break"

    def _delete_header_row(self, tab) -> None:
        tree = getattr(tab, "_headers_tree", None)
        if not tree:
            return
        selected = tree.selection()
        for item_id in selected:
            tree.delete(item_id)
        if selected:
            tab._builder_dirty = True
            tab.builder_dirty = True
            self._save_builder_state(tab)
            self._update_env_hint(tab)
            tab._status_lbl.config(text="Header đã xoá.", fg=TEXT_DIM)

    def _clear_header_rows(self, tab) -> None:
        tree = getattr(tab, "_headers_tree", None)
        if not tree:
            return
        tree.delete(*tree.get_children())
        tab._header_key_var.set("")
        tab._header_value_var.set("")
        tab._builder_dirty = True
        tab.builder_dirty = True
        self._save_builder_state(tab)
        self._update_env_hint(tab)
        tab._status_lbl.config(text="Headers đã xoá.", fg=TEXT_DIM)

    def _schedule_curl_parse(self, tab) -> None:
        if getattr(tab, "_builder_dirty", False):
            return
        after_id = getattr(tab, "_parse_after", None)
        if after_id:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        tab._parse_after = self.after(
            650,
            lambda t=tab: self._parse_curl_to_builder(t, switch=False, force=False, show_status=False),
        )

    def _parse_curl_to_builder(
        self,
        tab,
        switch: bool = False,
        force: bool = False,
        show_status: bool = False,
    ) -> bool:
        if not hasattr(tab, "_curl_tw") or not hasattr(tab, "_method_var"):
            return False
        if getattr(tab, "_builder_dirty", False) and not force:
            return False

        raw = tab._curl_tw.get("1.0", "end").strip()
        if not raw or getattr(tab, "_ph_active", False):
            return False
        if not raw.lower().lstrip().startswith("curl"):
            if show_status:
                tab._status_lbl.config(text="Input không bắt đầu bằng curl.", fg=TEXT_DIM)
            return False

        try:
            parsed = parse_curl(raw)
        except Exception as exc:
            if show_status:
                tab._status_lbl.config(text=f"Không parse được curl: {str(exc)[:90]}", fg=RED_C)
            return False

        self._fill_request_builder(tab, parsed, dirty=False)
        if switch and getattr(tab, "_request_frame", None):
            tab._nb.select(tab._request_frame)
        if show_status:
            tab._status_lbl.config(text="↘ Đã tách curl thành Method / URL / Headers / Body", fg=GREEN)
        self._update_env_hint(tab)
        return True

    def _fill_request_builder(self, tab, parsed: dict, dirty: bool = False) -> None:
        tab._syncing_builder = True
        try:
            if tab._method_var:
                tab._method_var.set(str(parsed.get("method") or "GET").upper())
            if tab._url_var:
                tab._url_var.set(str(parsed.get("url") or ""))
            self._set_header_rows(tab, (parsed.get("headers") or {}).items(), dirty=False)
            if tab._body_builder_tw:
                tab._body_builder_tw.delete("1.0", "end")
                tab._body_builder_tw.insert("1.0", self._body_to_builder_text(parsed.get("body")))
        finally:
            tab._syncing_builder = False
        body = parsed.get("body")
        # Những gì Request builder không hiển thị được: giữ lại để lúc gửi/lưu không bị mất.
        tab._parsed_extras = {
            "auth": parsed.get("auth"),
            "verify_ssl": parsed.get("verify_ssl", True),
            "timeout": parsed.get("timeout", DEFAULT_TIMEOUT),
            "body": None if body is None or isinstance(body, str) else body,
            "body_text": self._body_to_builder_text(body),
            "body_file": parsed.get("body_file"),
        }
        tab._builder_dirty = dirty
        tab.builder_dirty = dirty
        self._save_builder_state(tab)

    def _headers_to_text(self, headers: dict) -> str:
        return "\n".join(f"{k}: {v}" for k, v in (headers or {}).items())

    def _body_to_builder_text(self, body) -> str:
        if body is None:
            return ""
        if isinstance(body, bytes):
            return f"[binary body: {len(body):,} bytes]"
        if isinstance(body, dict):
            return "\n".join(f"{k}={v}" for k, v in body.items())
        return str(body)

    def _parse_headers_editor(self, text: str) -> dict[str, str]:
        headers: dict[str, str] = {}
        for line in (text or "").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if ":" not in raw:
                raise ValueError(f"Header không hợp lệ, cần dạng `Key: value`: {raw[:80]}")
            key, _, value = raw.partition(":")
            key = key.strip()
            if not key:
                raise ValueError(f"Header thiếu key: {raw[:80]}")
            headers[key] = value.strip()
        return headers

    def _builder_has_request(self, tab) -> bool:
        if not hasattr(tab, "_url_var") or tab._url_var is None:
            return False
        return bool(tab._url_var.get().strip())

    def _build_parsed_from_builder(self, tab, env: dict[str, str]) -> dict:
        self._save_builder_state(tab)
        method = (tab.builder_method or "GET").strip().upper()
        url = apply_env(tab.builder_url, env).strip()
        if not url:
            raise ValueError("URL trong Request tab đang trống.")
        headers_text = apply_env(tab.builder_headers, env)
        body_text = apply_env(tab.builder_body, env)
        body = body_text if body_text else None
        extras = getattr(tab, "_parsed_extras", None) or {}
        original_body = extras.get("body")
        if isinstance(original_body, dict) and self._looks_like_form(body_text):
            body = self._form_from_builder_text(body_text) or None
        elif isinstance(original_body, bytes) and tab.builder_body == extras.get("body_text"):
            body = original_body   # body nhị phân: builder chỉ hiển thị bản tóm tắt
        return {
            "method": method,
            "url": url,
            "headers": self._parse_headers_editor(headers_text),
            "body": body,
            "auth": extras.get("auth"),
            "verify_ssl": extras.get("verify_ssl", True),
            "allow_redirects": True,
            "timeout": extras.get("timeout", DEFAULT_TIMEOUT),
        }

    def _looks_like_form(self, text: str) -> bool:
        """Body của curl -F hiển thị dạng `key=value` mỗi dòng; JSON/text tự do thì không."""
        lines = [line for line in (text or "").splitlines() if line.strip()]
        return all("=" in line for line in lines) and not (text or "").lstrip().startswith(("{", "["))

    def _form_from_builder_text(self, text: str) -> dict[str, str]:
        form: dict[str, str] = {}
        for line in (text or "").splitlines():
            key, _, value = line.partition("=")
            if key.strip():
                form[key.strip()] = value
        return form

    def _build_curl_from_builder(self, tab) -> str:
        self._save_builder_state(tab)
        method = (tab.builder_method or "GET").strip().upper()
        url = tab.builder_url.strip()
        parts = ["curl"]
        if method != "GET" or tab.builder_body.strip():
            parts.append(f"-X {method}")
        if url:
            parts.append(shlex.quote(url))
        for key, value in self._parse_headers_editor(tab.builder_headers).items():
            parts.append(f"-H {shlex.quote(f'{key}: {value}')}")
        extras = getattr(tab, "_parsed_extras", None) or {}
        auth = extras.get("auth")
        if auth:
            parts.append(f"-u {shlex.quote(':'.join(str(x) for x in auth))}")
        original_body = extras.get("body")
        if isinstance(original_body, dict) and self._looks_like_form(tab.builder_body):
            for key, value in self._form_from_builder_text(tab.builder_body).items():
                parts.append(f"-F {shlex.quote(f'{key}={value}')}")
        elif (isinstance(original_body, bytes) and extras.get("body_file")
              and tab.builder_body == extras.get("body_text")):
            parts.append(f"--data-binary {shlex.quote('@' + extras['body_file'])}")
        elif tab.builder_body.strip():
            parts.append(f"--data-raw {shlex.quote(tab.builder_body.strip())}")
        if not extras.get("verify_ssl", True):
            parts.append("-k")
        timeout = extras.get("timeout", DEFAULT_TIMEOUT)
        if timeout != DEFAULT_TIMEOUT:
            parts.append(f"--max-time {timeout:g}")
        return " \\\n  ".join(parts)

    def _current_raw_curl(self, tab) -> str:
        if not hasattr(tab, "_curl_tw") or getattr(tab, "_ph_active", False):
            return ""
        return tab._curl_tw.get("1.0", "end").strip()

    def _storage_curl_for_tab(self, tab) -> str:
        raw = self._current_raw_curl(tab)
        if self._builder_has_request(tab) and (getattr(tab, "_builder_dirty", False) or not raw):
            return self._build_curl_from_builder(tab)
        return raw

    def _prepare_request_from_tab(self, tab, env: dict[str, str]) -> tuple[dict, str]:
        raw = self._current_raw_curl(tab)
        use_builder = self._builder_has_request(tab) and (getattr(tab, "_builder_dirty", False) or not raw)
        if use_builder:
            return self._build_parsed_from_builder(tab, env), self._build_curl_from_builder(tab)
        if not raw:
            raise ValueError("Vui lòng nhập curl command hoặc URL trong Request tab.")
        return parse_curl(apply_env(raw, env)), raw

    def _set_curl(self, curl_str, tests: str | None = None):
        """Load curl (và Tests nếu có) vào tab đang active."""
        if self.active_tab_idx < 0: return
        tab = self.tabs[self.active_tab_idx]
        if not hasattr(tab,"_curl_tw"): return
        if tests is not None and tab._tests_tw is not None:
            tab._tests_tw.delete("1.0", "end")
            tab._tests_tw.insert("1.0", tests)
            tab.tests = tests
        self._clear_ph(tab)
        tab._curl_tw.delete("1.0","end")
        tab._curl_tw.insert("1.0", curl_str)
        tab.curl = curl_str
        tab._builder_dirty = False
        tab.builder_dirty = False
        self._parse_curl_to_builder(tab, switch=True, force=True, show_status=False)
        self._update_env_hint(tab)

    def _update_env_hint(self, tab=None):
        if tab is None:
            if self.active_tab_idx < 0: return
            tab = self.tabs[self.active_tab_idx]
        if not hasattr(tab,"_curl_tw"): return
        texts = []
        if not getattr(tab, "_ph_active", False):
            texts.append(tab._curl_tw.get("1.0","end"))
        if hasattr(tab, "_url_var") and tab._url_var:
            texts.append(tab._url_var.get())
        if hasattr(tab, "_headers_tree") and tab._headers_tree:
            texts.append(self._headers_editor_to_text(tab))
        if hasattr(tab, "_body_builder_tw") and tab._body_builder_tw:
            texts.append(tab._body_builder_tw.get("1.0", "end"))
        text = "\n".join(texts)
        found = re.findall(r'\{\{(\w+)\}\}', text)
        lbl   = getattr(tab,"_env_hint_lbl", None)
        if not lbl: return
        if not found:
            lbl.config(text=""); return
        env = self.environments.get(self.active_env,{})
        ok  = [v for v in set(found) if v in env]
        bad = [v for v in set(found) if v not in env]
        parts = []
        if ok:  parts.append(f"✓ {', '.join(ok)}")
        if bad: parts.append(f"✗ {', '.join(bad)}")
        lbl.config(text="  ".join(parts), fg=RED_C if bad else GREEN)

    # ── Beautify ──────────────────────────────
    def _beautify_body(self, tab):
        if not hasattr(tab,"_curl_tw"): return
        self._clear_ph(tab)
        raw = tab._curl_tw.get("1.0","end").strip()
        if not raw:
            if hasattr(tab, "_body_builder_tw") and tab._body_builder_tw:
                body = tab._body_builder_tw.get("1.0", "end").strip()
                try:
                    pretty = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
                except Exception:
                    return
                tab._body_builder_tw.delete("1.0", "end")
                tab._body_builder_tw.insert("1.0", pretty)
                self._mark_builder_dirty(tab)
                tab._status_lbl.config(text="✨ Body đã được format", fg=GREEN)
            return
        result = beautify_curl_body(raw)
        if result != raw:
            tab._curl_tw.delete("1.0","end")
            tab._curl_tw.insert("1.0", result)
            tab._builder_dirty = False
            tab.builder_dirty = False
            self._parse_curl_to_builder(tab, switch=False, force=True, show_status=False)
            tab._status_lbl.config(text="✨ Body đã được format", fg=GREEN)
        else:
            tab._status_lbl.config(text="Body không phải JSON hoặc đã format rồi", fg=TEXT_DIM)

    # ── Script example ────────────────────────
    def _insert_script_example(self, tab):
        example = (
            "# ── Ví dụ 1: Set token thủ công ─────────────────\n"
            "set_env('token', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...')\n\n"
            "# ── Ví dụ 2: Lấy token từ API login ─────────────\n"
            "# resp = requests.post(env.get('base_url','') + '/auth/login',\n"
            "#     json={'username': 'admin', 'password': 'secret'},\n"
            "#     timeout=10)\n"
            "# if resp.ok:\n"
            "#     token = resp.json()['data']['token']\n"
            "#     set_env('token', token)\n"
            "#     log(f'Token: {token[:20]}...')\n"
            "# else:\n"
            "#     log(f'Login thất bại: {resp.status_code}')\n\n"
            "# ── Ví dụ 3: Tính timestamp ───────────────────────\n"
            "# import time\n"
            "# set_env('timestamp', str(int(time.time())))\n"
        )
        if hasattr(tab,"_pre_tw"):
            tab._pre_tw.delete("1.0","end")
            tab._pre_tw.insert("1.0", example)
            tab._pre_tw.config(fg=TEXT)

    # ── Tests (assertion sau response) ────────
    def _current_tests(self, tab) -> str:
        tw = getattr(tab, "_tests_tw", None)
        return tw.get("1.0", "end").strip() if tw is not None else (tab.tests or "")

    def _insert_tests_example(self, tab):
        example = (
            "# Mỗi dòng 1 điều kiện, dừng ở dòng FAIL đầu tiên\n"
            "status == 200\n"
            "time < 1000\n"
            "header Content-Type contains json\n"
            "json $.data exists\n"
            "# json $.data.items[0].id == {{user_id}}\n"
            "# body not_contains error\n\n"
            "# Lưu giá trị vào environment đang chọn, dùng lại bằng {{token}}\n"
            "# token = json:$.data.token\n"
            "# request_id = header:X-Request-Id\n"
        )
        if getattr(tab, "_tests_tw", None) is not None:
            tab._tests_tw.delete("1.0", "end")
            tab._tests_tw.insert("1.0", example)

    def _run_request_tests(self, tab, resp, body_text: str, elapsed: float, env: dict) -> tuple[list[str], bool | None]:
        """Chạy Tests của tab trên response. Trả về (dòng kết quả, True/False; None nếu không có test)."""
        extract_rules, assert_rules = split_test_rules(self._current_tests(tab))
        if not extract_rules and not assert_rules:
            return [], None
        lines: list[str] = []
        ok = True
        try:
            if extract_rules:
                values, logs = extract_values(apply_env(extract_rules, env), resp, body_text)
                lines.extend(logs)
                if values:
                    target = self.environments.setdefault(self.active_env, {})
                    target.update(values)
                    store.save_environments(self.environments)
                    lines.append(f"→ đã lưu vào environment '{self.active_env}': {', '.join(sorted(values))}")
            if assert_rules:
                passed, details = evaluate_assertions(apply_env(assert_rules, env), resp, body_text, elapsed)
                lines.extend(details)
                ok = passed
        except Exception as exc:   # rule sai cú pháp, body không phải JSON...
            lines.append(f"ERROR: {exc}")
            ok = False
        return lines, ok

    def _write_tests(self, tab) -> None:
        w = self.tests_tw
        w.config(state="normal"); w.delete("1.0", "end")
        if not tab.test_results:
            w.insert("end", "  Chưa có test. Thêm điều kiện ở tab ✅ Tests của request (vd: status == 200).", "dim")
        else:
            for line in tab.test_results:
                if line.startswith(("FAIL", "ERROR")):
                    tag = "err"
                elif line.startswith(("PASS", "→")):
                    tag = "ok"
                else:
                    tag = "dim"
                w.insert("end", f"  {line}\n", tag)
        w.config(state="disabled")
        if self.rtab_tests:
            mark = "" if tab.test_ok is None else (" ✓" if tab.test_ok else " ✗")
            self.rtab_tests.config(text=f"Tests{mark}")

    # ── Import file ───────────────────────────
    def _import_file(self, tab=None):
        if tab is None:
            if self.active_tab_idx < 0: return
            tab = self.tabs[self.active_tab_idx]
        path = filedialog.askopenfilename(
            title="Chọn file curl",
            filetypes=[("Text/Shell","*.txt *.sh *.curl"),("All","*.*")])
        if not path: return
        try:
            with open(path,"r",encoding="utf-8") as f: content = f.read().strip()
            lines, out, found = content.splitlines(), [], False
            for line in lines:
                s = line.strip()
                if s.lower().startswith("curl "): found = True
                if found:
                    out.append(line)
                    if not s.endswith("\\") and not s.endswith("^"): break
            self._clear_ph(tab)
            tab._curl_tw.delete("1.0","end")
            tab._curl_tw.insert("1.0", "\n".join(out) if out else content)
            tab._builder_dirty = False
            tab.builder_dirty = False
            self._parse_curl_to_builder(tab, switch=True, force=True, show_status=False)
            tab._status_lbl.config(text=f"📂 Đã import: {Path(path).name}", fg=GREEN)
            self._update_env_hint(tab)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không đọc được file:\n{e}")

    def _clear_input(self, tab):
        if not hasattr(tab,"_curl_tw"): return
        tab._curl_tw.delete("1.0","end")
        if hasattr(tab, "_method_var") and tab._method_var:
            tab._syncing_builder = True
            try:
                tab._method_var.set("GET")
                tab._url_var.set("")
                if getattr(tab, "_headers_tree", None):
                    tab._headers_tree.delete(*tab._headers_tree.get_children())
                if getattr(tab, "_header_key_var", None):
                    tab._header_key_var.set("")
                if getattr(tab, "_header_value_var", None):
                    tab._header_value_var.set("")
                tab._body_builder_tw.delete("1.0", "end")
            finally:
                tab._syncing_builder = False
            tab._builder_dirty = False
            tab.builder_dirty = False
            tab._parsed_extras = {}
            self._save_builder_state(tab)
        self._restore_ph(tab)
        tab._status_lbl.config(text="")
        if hasattr(tab,"_env_hint_lbl"):
            tab._env_hint_lbl.config(text="")

    def _save_tab_to_coll(self, tab):
        if not hasattr(tab,"_curl_tw"): return
        try:
            curl_str = self._storage_curl_for_tab(tab)
        except Exception as exc:
            messagebox.showwarning("", f"Request chưa hợp lệ:\n{exc}"); return
        if not curl_str:
            messagebox.showwarning("","Hãy nhập curl command hoặc URL trong Request tab."); return
        if not self.collections:
            if messagebox.askyesno("Chưa có Collection","Tạo mới?"):
                self._new_collection()
        self._save_to_coll_dialog(curl_str, tests=self._current_tests(tab))

    # ── SEND ──────────────────────────────────
    def _get_repeat_count(self, tab) -> int:
        raw = tab._repeat_var.get().strip() if hasattr(tab, "_repeat_var") else "1"
        try:
            value = int(raw)
        except Exception:
            raise ValueError("Repeat phải là số nguyên >= 1")
        if value < 1:
            raise ValueError("Repeat phải >= 1")
        if value > 1000:
            raise ValueError("Repeat tối đa là 1000 để tránh gọi API quá nhiều.")
        return value

    def _send(self, tab):
        if not hasattr(tab,"_curl_tw"): return
        self._save_tab_state(tab)
        curl_str = self._current_raw_curl(tab)
        if not curl_str and not self._builder_has_request(tab):
            messagebox.showwarning("Thiếu input","Vui lòng nhập curl command hoặc URL trong Request tab."); return
        try:
            repeat_count = self._get_repeat_count(tab)
        except ValueError as e:
            messagebox.showwarning("Repeat không hợp lệ", str(e)); return

        # Run pre-request script
        env = dict(self.environments.get(self.active_env,{}))
        pre_script = tab._pre_tw.get("1.0","end").strip() if hasattr(tab,"_pre_tw") else ""
        pre_logs = []
        if has_executable_code(pre_script):
            env, pre_logs = run_pre_script(pre_script, env)
            tab.pre_logs = pre_logs

        try:
            parsed = None
            parsed, original_curl = self._prepare_request_from_tab(tab, env)
            # -k / --max-time trong curl được ưu tiên hơn giá trị mặc định của các ô option.
            parsed["verify_ssl"]      = bool(parsed.get("verify_ssl", True)) and tab._var_ssl.get()
            parsed["allow_redirects"] = tab._var_redirect.get()
            if parsed.get("timeout", DEFAULT_TIMEOUT) == DEFAULT_TIMEOUT:
                try:
                    timeout = float(tab._timeout_var.get())
                except ValueError:
                    timeout = DEFAULT_TIMEOUT
                parsed["timeout"] = timeout if timeout > 0 else DEFAULT_TIMEOUT
        except Exception as e:
            messagebox.showwarning("Request không hợp lệ", str(e)); return

        btn_text = "⏳  Đang gửi..." if repeat_count == 1 else f"⏳  Gửi 1/{repeat_count}..."
        tab._send_btn.config(state="disabled", text=btn_text)
        tab._status_lbl.config(
            text="Đang gửi..." if repeat_count == 1 else f"Auto call: 1/{repeat_count}",
            fg=TEXT_DIM
        )
        self.status_badge.config(text="...", fg=TEXT_DIM, bg=BG3)
        self.time_label.config(text=""); self.size_label.config(text="")

        def worker():
            try:
                repeat_logs = []
                resp = None
                elapsed = 0
                for attempt in range(1, repeat_count + 1):
                    self._ui.post(lambda a=attempt: (
                        tab._send_btn.config(text=f"⏳  Gửi {a}/{repeat_count}..."),
                        tab._status_lbl.config(text=f"Auto call: {a}/{repeat_count}", fg=TEXT_DIM)
                    ))
                    resp, elapsed = execute_request(parsed)
                    if repeat_count > 1:
                        repeat_logs.append(
                            f"🔁 Attempt {attempt}/{repeat_count}: "
                            f"{resp.status_code} {resp.reason} · {elapsed:.0f} ms"
                        )
                logs = list(pre_logs)
                if repeat_logs:
                    logs.append(f"🔁 Auto call complete: {repeat_count} request(s)")
                    logs.extend(repeat_logs)
                self._ui.post(lambda: self._display(
                    tab, parsed, resp, elapsed, original_curl, logs, repeat_count, env
                ))
            except Exception as e:
                error_msg = str(e) or repr(e) or e.__class__.__name__
                self._ui.post(lambda error_msg=error_msg: self._show_error(tab, error_msg))

        threading.Thread(target=worker, daemon=True).start()

    # ══ RIGHT PANEL (RESPONSE) ════════════════
    def _build_right(self, parent):
        frame = tk.Frame(parent, bg=BG, padx=12, pady=10)

        ss = tk.Frame(frame, bg=BG)
        ss.pack(fill="x", pady=(0,8))
        self._sec(ss, "RESPONSE", side="left")
        self.status_badge = tk.Label(ss, text="-", font=self.fn_stat, bg=BG3, fg=TEXT_DIM,
                                     padx=10, pady=3)
        self.status_badge.pack(side="left", padx=(14,4))
        self.time_label = tk.Label(ss, text="", font=self.fn_label, bg=BG3, fg=TEXT_DIM,
                                   padx=8, pady=4)
        self.time_label.pack(side="left", padx=6)
        self.size_label = tk.Label(ss, text="", font=self.fn_label, bg=BG3, fg=TEXT_DIM,
                                   padx=8, pady=4)
        self.size_label.pack(side="left", padx=6)
        self._mkbtn(ss, "Copy", self._copy_response, side="right")
        self._mkbtn(ss, "Save", self._save_response,  side="right", pad=(0,6))
        self.ai_analyze_btn = self._mkbtn(ss, "AI Analyze", self._analyze_response, side="right", pad=(0,6))

        ai_opts = tk.Frame(frame, bg=BG3)
        ai_opts.pack(fill="x", pady=(0,6))
        tk.Label(ai_opts, text="AI Analysis:", font=self.fn_label, bg=BG3,
                 fg=TEXT_DIM).pack(side="left", padx=(9,8), pady=5)
        for text, value in [("Free Local", "ollama"), ("Billing API", "openai")]:
            tk.Radiobutton(
                ai_opts, text=text, value=value,
                variable=self.ai_provider_var,
                command=self._on_ai_provider_change,
                font=self.fn_label, bg=BG3, fg=TEXT_DIM,
                activebackground=BG3, activeforeground=TEXT,
                selectcolor=BG2, bd=0, padx=8,
            ).pack(side="left")
        self.ai_status_lbl = tk.Label(ai_opts, text="Ollama: checking...",
                                      font=self.fn_small, bg=BG3,
                                      fg=TEXT_DIM, anchor="e")
        self.ai_status_lbl.pack(side="right", padx=(8, 9))

        toolbar = tk.Frame(frame, bg=BG)
        toolbar.pack(fill="x", pady=(0,4))
        tr = tk.Frame(toolbar, bg=BORDER)
        tr.pack(side="left")
        for lbl, val in [("Body","body"),("Headers","headers"),("Info","info"),("Log","log"),
                         ("Tests","tests"),("AI","ai")]:
            btn = tk.Button(tr, text=lbl, font=self.fn_label,
                            bg=SURFACE_ACTIVE if val=="body" else BG3,
                            fg=ACTIVE_TEXT if val=="body" else TEXT_DIM,
                            relief="flat", cursor="hand2", padx=14, pady=6,
                            command=lambda v=val: self._show_resp_tab(v), bd=0)
            btn.pack(side="left", padx=(1,0), pady=1)
            if val == "body":       self.rtab_body    = btn
            elif val == "headers":  self.rtab_headers = btn
            elif val == "info":     self.rtab_info    = btn
            elif val == "log":      self.rtab_log     = btn
            elif val == "tests":    self.rtab_tests   = btn
            elif val == "ai":       self.rtab_ai      = btn

        search = tk.Frame(frame, bg=BG3)
        search.pack(fill="x", pady=(0,6))
        tk.Label(search, text="Search", font=self.fn_label, bg=BG3,
                 fg=TEXT_DIM).pack(side="left", padx=(9,5))
        self.resp_search_var = tk.StringVar()
        self.resp_case_var = tk.BooleanVar(value=False)
        self.resp_search_var.trace_add("write", self._schedule_response_search)
        self.resp_search_entry = tk.Entry(
            search, textvariable=self.resp_search_var, font=self.fn_monos,
            bg=BG2, fg=TEXT, insertbackground=ACCENT, relief="flat",
            bd=0, width=18
        )
        self.resp_search_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.resp_search_entry.bind("<Return>", lambda e: self._goto_response_match(1))
        self.resp_search_entry.bind("<Shift-Return>", lambda e: self._goto_response_match(-1))
        self.resp_search_entry.bind("<Escape>", lambda e: self._clear_response_search())
        self.resp_search_count_lbl = tk.Label(search, text="", font=self.fn_small,
                                              bg=BG3, fg=TEXT_DIM, width=8)
        self.resp_search_count_lbl.pack(side="left", padx=(6,2))
        self._mkbtn(search, "Prev", lambda: self._goto_response_match(-1), side="left", pad=(0,2))
        self._mkbtn(search, "Next", lambda: self._goto_response_match(1), side="left", pad=(0,2))
        tk.Checkbutton(
            search, text="Aa", variable=self.resp_case_var,
            command=self._schedule_response_search,
            font=self.fn_small, bg=BG3, fg=TEXT_DIM,
            activebackground=BG3, activeforeground=TEXT,
            selectcolor=BG2, bd=0, padx=4
        ).pack(side="left", padx=(0,4))
        self.bind_all("<Control-f>", self._focus_response_search, add="+")

        self.resp_content = tk.Frame(frame, bg=BG)
        self.resp_content.pack(fill="both", expand=True, pady=(4,0))
        self._mk_text_tab("body",    self.fn_mono)
        self._mk_text_tab("headers", self.fn_monos)
        self._mk_text_tab("info",    self.fn_monos)
        self._mk_text_tab("log",     self.fn_monos)
        self._mk_text_tab("tests",   self.fn_monos)
        self._mk_text_tab("ai",      self.fn_monos)

        self.body_tw.tag_configure("key",   foreground=CYAN_C)
        self.body_tw.tag_configure("str",   foreground=GREEN)
        self.body_tw.tag_configure("num",   foreground=YELLOW_C)
        self.body_tw.tag_configure("bool",  foreground=MAG_C)
        self.body_tw.tag_configure("plain", foreground=TEXT)
        self.headers_tw.tag_configure("hk", foreground=CYAN_C)
        self.headers_tw.tag_configure("hv", foreground=TEXT)
        self.info_tw.tag_configure("lbl",    foreground=TEXT_DIM)
        self.info_tw.tag_configure("val",    foreground=TEXT)
        self.info_tw.tag_configure("method", foreground=ACCENT)
        self.info_tw.tag_configure("url",    foreground=TEXT_URL)
        self.log_tw.tag_configure("ok",  foreground=GREEN)
        self.log_tw.tag_configure("err", foreground=RED_C)
        self.log_tw.tag_configure("dim", foreground=TEXT_DIM)
        self.ai_tw.tag_configure("plain", foreground=TEXT)
        self.ai_tw.tag_configure("dim", foreground=TEXT_DIM)
        self.ai_tw.tag_configure("err", foreground=RED_C)
        self.tests_tw.tag_configure("ok",  foreground=GREEN)
        self.tests_tw.tag_configure("err", foreground=RED_C)
        self.tests_tw.tag_configure("dim", foreground=TEXT_DIM)
        for tw in self._response_text_widgets():
            tw.tag_configure("search_match", background="#ffe4d6", foreground=TEXT)
            tw.tag_configure("search_current", background=ACCENT, foreground=ACTIVE_TEXT)
            tw.tag_raise("search_current")

        self._show_resp_tab("body")
        return frame

    def _mk_text_tab(self, name: str, fnt: tkfont.Font) -> None:
        frame = tk.Frame(self.resp_content, bg=BG)
        wrap  = tk.Frame(frame, bg=BORDER)
        wrap.pack(fill="both", expand=True)
        tw = tk.Text(wrap, bg=BG2, fg=TEXT, font=fnt,
                     wrap="word", relief="flat", padx=10, pady=8,
                     selectbackground=ACCENT, selectforeground=ACTIVE_TEXT,
                     state="disabled", bd=0)
        sb = tk.Scrollbar(wrap, command=tw.yview, bg=BG3, troughcolor=BG2, bd=0)
        tw.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); tw.pack(fill="both", expand=True, padx=1, pady=1)
        # Gán trực tiếp thay vì setattr để Pylance track được
        if name == "body":
            self.body_frame = frame; self.body_tw = tw
        elif name == "headers":
            self.headers_frame = frame; self.headers_tw = tw
        elif name == "info":
            self.info_frame = frame; self.info_tw = tw
        elif name == "log":
            self.log_frame = frame; self.log_tw = tw
        elif name == "tests":
            self.tests_frame = frame; self.tests_tw = tw
        elif name == "ai":
            self.ai_frame = frame; self.ai_tw = tw

    def _show_resp_tab(self, val: str) -> None:
        self.active_resp_tab = val
        _frames = {"body": self.body_frame, "headers": self.headers_frame,
                   "info": self.info_frame, "log": self.log_frame,
                   "tests": self.tests_frame, "ai": self.ai_frame}
        _btns   = {"body": self.rtab_body, "headers": self.rtab_headers,
                   "info": self.rtab_info, "log": self.rtab_log,
                   "tests": self.rtab_tests, "ai": self.rtab_ai}
        for v, frame in _frames.items():
            if frame: frame.pack_forget()
            btn = _btns.get(v)
            if btn: btn.config(
                bg=SURFACE_ACTIVE if v==val else BG3,
                fg=ACTIVE_TEXT if v==val else TEXT_DIM)
        target = _frames.get(val)
        if target: target.pack(fill="both", expand=True)
        self._schedule_response_search()

    def _response_text_widgets(self) -> list[tk.Text]:
        return [w for w in (self.body_tw, self.headers_tw, self.info_tw, self.log_tw,
                            self.tests_tw, self.ai_tw) if w]

    def _active_response_widget(self) -> tk.Text:
        return getattr(self, f"{self.active_resp_tab}_tw", self.body_tw)

    def _focus_response_search(self, _event=None):
        if self.resp_search_entry:
            self.resp_search_entry.focus_set()
            self.resp_search_entry.selection_range(0, "end")
        return "break"

    def _clear_response_search(self):
        if self.resp_search_var:
            self.resp_search_var.set("")
        self.response_matches = []
        self.response_match_index = -1
        self.response_match_overflow = False
        self._clear_response_search_tags()
        self._update_response_search_count()
        return "break"

    def _schedule_response_search(self, *_):
        if not getattr(self, "resp_search_count_lbl", None):
            return
        if self.response_search_after:
            self.after_cancel(self.response_search_after)
        self.response_search_after = self.after(120, self._run_response_search)

    def _clear_response_search_tags(self, widget: tk.Text | None = None) -> None:
        widgets = [widget] if widget else self._response_text_widgets()
        for w in widgets:
            old_state = str(w.cget("state"))
            if old_state == "disabled":
                w.config(state="normal")
            w.tag_remove("search_match", "1.0", "end")
            w.tag_remove("search_current", "1.0", "end")
            if old_state == "disabled":
                w.config(state="disabled")

    def _run_response_search(self) -> None:
        self.response_search_after = None
        query = self.resp_search_var.get() if self.resp_search_var else ""
        self.response_matches = []
        self.response_match_index = -1
        self.response_match_overflow = False
        self._clear_response_search_tags()

        if not query:
            self._update_response_search_count()
            return

        w = self._active_response_widget()
        text = w.get("1.0", "end-1c")
        if not text:
            self._update_response_search_count()
            return

        needle = query if self.resp_case_var.get() else query.lower()
        haystack = text if self.resp_case_var.get() else text.lower()
        start = 0
        q_len = len(query)
        matches: list[tuple[str, str]] = []
        overflow = False

        old_state = str(w.cget("state"))
        if old_state == "disabled":
            w.config(state="normal")

        while True:
            hit = haystack.find(needle, start)
            if hit < 0:
                break
            start_index = f"1.0+{hit}c"
            end_index = f"1.0+{hit + q_len}c"
            matches.append((start_index, end_index))
            w.tag_add("search_match", start_index, end_index)
            start = hit + q_len
            if len(matches) >= self.SEARCH_HIGHLIGHT_LIMIT:
                overflow = haystack.find(needle, start) >= 0
                break

        w.tag_raise("search_match")
        w.tag_raise("search_current")
        if old_state == "disabled":
            w.config(state="disabled")

        self.response_matches = matches
        self.response_match_overflow = overflow
        if matches:
            self.response_match_index = 0
            self._mark_response_current()
        else:
            self._update_response_search_count()

    def _goto_response_match(self, step: int):
        if not (self.resp_search_var and self.resp_search_var.get()):
            return self._focus_response_search()
        if not self.response_matches:
            self._run_response_search()
        if not self.response_matches:
            return "break"
        if self.response_match_index < 0:
            self.response_match_index = 0
        else:
            self.response_match_index = (self.response_match_index + step) % len(self.response_matches)
        self._mark_response_current()
        return "break"

    def _mark_response_current(self) -> None:
        if not self.response_matches:
            self._update_response_search_count()
            return
        w = self._active_response_widget()
        old_state = str(w.cget("state"))
        if old_state == "disabled":
            w.config(state="normal")
        w.tag_remove("search_current", "1.0", "end")
        start, end = self.response_matches[self.response_match_index]
        w.tag_add("search_current", start, end)
        w.tag_raise("search_current")
        if old_state == "disabled":
            w.config(state="disabled")
        w.see(start)
        self._update_response_search_count()

    def _update_response_search_count(self) -> None:
        if not getattr(self, "resp_search_count_lbl", None):
            return
        query = self.resp_search_var.get() if self.resp_search_var else ""
        if not query:
            self.resp_search_count_lbl.config(text="")
        elif not self.response_matches:
            self.resp_search_count_lbl.config(text="0/0")
        else:
            total = f"{len(self.response_matches)}+" if self.response_match_overflow else str(len(self.response_matches))
            self.resp_search_count_lbl.config(text=f"{self.response_match_index + 1}/{total}")

    def _clear_response_panel(self):
        self.status_badge.config(text="-", fg=TEXT_DIM, bg=BG3)
        self.time_label.config(text=""); self.size_label.config(text="")
        for name in ("body","headers","info","log","tests","ai"):
            w = getattr(self, f"{name}_tw")
            w.config(state="normal"); w.delete("1.0","end"); w.config(state="disabled")
        if self.rtab_tests:
            self.rtab_tests.config(text="Tests")
        self.response_matches = []
        self.response_match_index = -1
        self.response_match_overflow = False
        self._clear_response_search_tags()
        self._update_response_search_count()

    def _restore_response(self, tab):
        if tab.response is None: return
        resp    = tab.response
        sc      = resp.status_code
        elapsed = tab.elapsed or 0
        size    = len(resp.content)
        self.status_badge.config(text=f"{sc} {resp.reason}", bg=status_color(sc), fg=STATUS_TEXT)
        self.time_label.config(text=f"{elapsed:.0f} ms", fg=YELLOW_C)
        sz = f"{size:,} B" if size < 1024 else f"{size/1024:.1f} KB"
        self.size_label.config(text=sz, fg=TEXT_DIM)
        self._write_body(tab.body_text, resp.headers.get("Content-Type",""))
        self._write_headers(resp.headers)
        self._write_info(tab.parsed, resp, elapsed, tab.detected_enc)
        self._write_log(tab.pre_logs)
        self._write_tests(tab)
        self._write_ai_analysis(tab.ai_analysis)
        self._schedule_response_search()

    # ── Display response ──────────────────────
    def _history_value(self, text: str, env: dict | None, is_url: bool = False) -> str:
        if not self.settings.get("redact_history", True):
            return text
        secrets = self._current_secret_map(env)
        return redact_url(text, secrets) if is_url else redact_curl(text, secrets)

    def _is_active_tab(self, tab) -> bool:
        return 0 <= self.active_tab_idx < len(self.tabs) and self.tabs[self.active_tab_idx] is tab

    def _display(self, tab, parsed, resp, elapsed, original_curl, pre_logs, repeat_count: int = 1,
                 env: dict | None = None):
        tab.response = resp
        tab.parsed   = parsed
        tab.elapsed  = elapsed
        tab.pre_logs = pre_logs
        tab.ai_analysis = ""

        sc   = resp.status_code
        body_text, enc_info = decode_response(resp, tab._var_decode.get())

        tab.body_text    = body_text
        tab.detected_enc = enc_info
        tab.test_results, tab.test_ok = self._run_request_tests(tab, resp, body_text, elapsed, env or {})

        if tab in self.tabs:   # tab có thể đã bị đóng trong lúc request đang chạy
            tab._send_btn.config(state="normal", text="▶  SEND REQUEST")
            url_s = parsed['url'][:52] + ("..." if len(parsed['url'])>52 else "")
            if repeat_count > 1:
                tab._status_lbl.config(
                    text=f"✓  Auto call complete: {repeat_count}x  ·  latest {parsed['method']} → {url_s}",
                    fg=GREEN
                )
            else:
                tab._status_lbl.config(text=f"✓  {parsed['method']}  →  {url_s}", fg=GREEN)
            if tab.test_ok is not None:
                current = tab._status_lbl.cget("text")
                verdict = "Tests PASS" if tab.test_ok else "Tests FAIL"
                tab._status_lbl.config(text=f"{current}  ·  {verdict}", fg=GREEN if tab.test_ok else RED_C)

        # Chỉ vẽ lên response panel dùng chung nếu tab này vẫn đang được chọn;
        # nếu không, response sẽ được hiển thị khi người dùng quay lại tab.
        if self._is_active_tab(tab):
            self._restore_response(tab)
            # Auto-show Script Log tab if script ran; test lỗi thì ưu tiên tab Tests
            if tab.test_ok is False:
                self._show_resp_tab("tests")
            elif pre_logs:
                self._show_resp_tab("log")

        # History
        self.history.append({
            "id":      str(uuid.uuid4())[:8],
            "ts":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "method":  parsed["method"], "url": self._history_value(parsed["url"], env, is_url=True),
            "curl":    self._history_value(original_curl, env), "status": sc,
            "elapsed": round(elapsed),
            "repeat":  repeat_count,
        })
        self.history = self.history[-500:]
        store.save_history(self.history)
        self._refresh_history_list()

    # ── Write panels ──────────────────────────
    def _write_body(self, text, ct):
        w = self.body_tw
        w.config(state="normal"); w.delete("1.0","end")
        render_text = text
        if len(render_text) > self.RESPONSE_PREVIEW_LIMIT:
            skipped = len(render_text) - self.RESPONSE_PREVIEW_LIMIT
            render_text = (
                render_text[:self.RESPONSE_PREVIEW_LIMIT]
                + f"\n\n[Preview truncated. {skipped:,} more characters are available via Save.]"
            )

        looks_json = "application/json" in ct.lower() or render_text.lstrip().startswith(("{","["))
        if looks_json and len(text) <= self.JSON_PRETTY_LIMIT:
            try:
                pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
                if len(pretty) <= self.JSON_HIGHLIGHT_LIMIT:
                    self._insert_json(w, pretty)
                else:
                    w.insert("end", pretty, "plain")
            except Exception:
                w.insert("end", render_text, "plain")
        else:
            w.insert("end", render_text, "plain")
        w.config(state="disabled")

    def _insert_json(self, w, text):
        base = w.index("end-1c")
        w.insert("end", text, "plain")
        TOKEN_RE = re.compile(
            r'("(?:[^"\\]|\\.)*")'
            r'|(-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?)'
            r'|(true|false|null)'
            r'|([{}\[\]:,])'
            r'|(\s+)'
        )
        expect_key = True
        for m in TOKEN_RE.finditer(text):
            s,n,kw,p,sp = m.groups()
            if sp:
                continue
            if p:
                if p in ('{',','): expect_key = True
                elif p == ':':     expect_key = False
            elif s:
                w.tag_add("key" if expect_key else "str",
                          f"{base}+{m.start()}c", f"{base}+{m.end()}c")
                if expect_key: expect_key = False
            elif n:
                w.tag_add("num", f"{base}+{m.start()}c", f"{base}+{m.end()}c")
            elif kw:
                w.tag_add("bool", f"{base}+{m.start()}c", f"{base}+{m.end()}c")

    def _write_headers(self, headers):
        w = self.headers_tw
        w.config(state="normal"); w.delete("1.0","end")
        for k,v in headers.items():
            w.insert("end", k, "hk"); w.insert("end", f": {v}\n", "hv")
        w.config(state="disabled")

    def _write_info(self, parsed, resp, elapsed, enc_info=""):
        w = self.info_tw
        w.config(state="normal"); w.delete("1.0","end")
        def row(lbl, val, tag="val"):
            w.insert("end", f"  {lbl:<22}","lbl")
            w.insert("end", f"{val}\n", tag)
        w.insert("end","  ── Request ─────────────────────────────\n","lbl")
        row("Method",  parsed["method"],  "method")
        secrets = self._current_secret_map()
        def hide(text):
            return replace_secret_values(str(text), secrets, MASK)
        row("URL",     hide(parsed["url"]), "url")
        row("Env",     self.active_env)
        if parsed["headers"]:
            w.insert("end","\n  ── Request Headers ──────────────────────\n","lbl")
            for k,v in parsed["headers"].items(): row(f"  {k}", hide(v))
        if parsed["body"] and not isinstance(parsed["body"], bytes):
            w.insert("end","\n  ── Request Body ─────────────────────────\n","lbl")
            w.insert("end", f"  {hide(str(parsed['body'])[:500])}\n","val")
        w.insert("end","\n  ── Response ─────────────────────────────\n","lbl")
        row("Status",   f"{resp.status_code} {resp.reason}")
        row("Time",     f"{elapsed:.0f} ms")
        row("Size",     f"{len(resp.content):,} bytes")
        row("Encoding", enc_info)
        w.config(state="disabled")

    def _write_log(self, logs: list):
        w = self.log_tw
        w.config(state="normal"); w.delete("1.0","end")
        if not logs:
            w.insert("end","  (Script không có output hoặc chưa chạy)","dim")
        else:
            for line in logs:
                tag = "ok" if line.startswith("✅") else ("err" if line.startswith("❌") else "dim")
                w.insert("end", f"  {line}\n", tag)
        w.config(state="disabled")

    def _write_ai_analysis(self, text: str, tag: str = "plain"):
        w = self.ai_tw
        w.config(state="normal"); w.delete("1.0","end")
        if text:
            w.insert("end", text, tag)
        else:
            w.insert("end", "  No AI analysis yet.", "dim")
        w.config(state="disabled")
        self._schedule_response_search()

    def _get_openai_key(self) -> str:
        key = os.environ.get("OPENAI_API_KEY") or self.openai_api_key
        if key:
            return key
        key = simpledialog.askstring(
            "Billing API key",
            "Nhập OpenAI API key để dùng Billing API:",
            parent=self,
            show="*",
        )
        if key:
            self.openai_api_key = key.strip()
        return self.openai_api_key

    def _on_ai_provider_change(self) -> None:
        if self.ai_provider_var.get() != "openai":
            self._refresh_ollama_status_async()
            return
        if self._get_openai_key():
            if self.ai_status_lbl:
                self.ai_status_lbl.config(text="OpenAI billing", fg=TEXT_DIM)
            return
        self.ai_provider_var.set("ollama")
        self._refresh_ollama_status_async()
        messagebox.showinfo("", "Chưa nhập API key. Đã chuyển về Free Local.")

    def _refresh_ollama_status_async(self) -> None:
        if not self.ai_status_lbl:
            return
        if self.ai_provider_var.get() != "ollama":
            self.ai_status_lbl.config(text="OpenAI billing", fg=TEXT_DIM)
            return
        self.ai_status_lbl.config(text="Ollama: checking...", fg=TEXT_DIM)
        model = os.environ.get("OLLAMA_MODEL", "")
        base_url = os.environ.get("OLLAMA_BASE_URL", OLLAMA_DEFAULT_BASE_URL)

        def worker() -> None:
            status = get_ollama_status(model, base_url)
            self._ui.post(lambda status=status: self._set_ollama_status_badge(status))

        threading.Thread(target=worker, daemon=True).start()

    def _set_ollama_status_badge(self, status: dict) -> None:
        if not self.ai_status_lbl:
            return
        if status.get("ready"):
            text = f"Ollama: ready ({status.get('selected_model')})"
            color = GREEN
        elif status.get("needs_install"):
            text = "Ollama: not installed"
            color = RED_C
        elif status.get("needs_start"):
            text = "Ollama: stopped"
            color = YELLOW_C
        elif status.get("needs_model"):
            text = "Ollama: need model"
            color = YELLOW_C
        else:
            text = "Ollama: not ready"
            color = RED_C
        self.ai_status_lbl.config(text=text, fg=color)

    def _format_ollama_setup_message(self, status: dict) -> str:
        lines = [
            "Ollama local chưa sẵn sàng cho Free Local AI.",
            "",
            f"Trạng thái: {status.get('message', 'Unknown')}",
            f"Base URL: {status.get('base_url', OLLAMA_DEFAULT_BASE_URL)}",
            f"Ollama CLI: {status.get('cli_path') or '(chưa tìm thấy)'}",
            f"Server: {'running' if status.get('api_running') else 'not running'}",
            f"Model cần dùng: {status.get('target_model') or 'llama3.2'}",
            "",
            "Mình đã mở cửa sổ setup để bạn Install / Start / Pull model và xem tiến độ.",
        ]
        if status.get("api_error") and not status.get("api_running"):
            lines.insert(-2, f"API detail: {status.get('api_error')}")
        return "\n".join(lines)

    def _open_ollama_setup(
        self,
        base_url: str,
        model: str,
        status: dict | None = None,
        on_ready=None,
    ) -> None:
        if self.ollama_setup_win and self.ollama_setup_win.winfo_exists():
            self.ollama_setup_win.lift()
            self.ollama_setup_win.focus_force()
            return

        def ready_callback() -> None:
            self._refresh_ollama_status_async()
            if on_ready:
                self.after(100, on_ready)

        self.ollama_setup_win = OllamaSetupWindow(
            self,
            base_url=base_url,
            preferred_model=model,
            initial_status=status,
            on_ready=ready_callback,
        )

    def _resolve_ai_provider(self) -> tuple[str, str, str]:
        provider = self.ai_provider_var.get().strip().lower()
        if provider not in ("ollama", "openai"):
            provider = "ollama"

        if provider == "openai":
            api_key = self._get_openai_key()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is required when AI_PROVIDER=openai.")
            return "openai", os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"), api_key

        return (
            "ollama",
            os.environ.get("OLLAMA_MODEL", ""),
            os.environ.get("OLLAMA_BASE_URL", OLLAMA_DEFAULT_BASE_URL),
        )

    def _analyze_response(self):
        if self.active_tab_idx < 0:
            return
        tab = self.tabs[self.active_tab_idx]
        if tab.response is None:
            messagebox.showinfo("", "Hãy gửi request trước."); return

        try:
            provider, model, credential = self._resolve_ai_provider()
        except Exception as e:
            self._show_resp_tab("ai")
            self._write_ai_analysis(f"AI analysis failed:\n{e}", "err")
            return

        if provider == "ollama":
            status = get_ollama_status(model, credential)
            self._set_ollama_status_badge(status)
            if not status.get("ready"):
                self._show_resp_tab("ai")
                self._write_ai_analysis(self._format_ollama_setup_message(status), "err")
                self._open_ollama_setup(
                    base_url=credential,
                    model=status.get("target_model") or model,
                    status=status,
                    on_ready=self._analyze_response,
                )
                return

        context = build_ai_response_context(
            tab.parsed or {}, tab.response, tab.body_text, tab.detected_enc
        )
        # Ngoài các key nhạy cảm (đã che sẵn), che luôn giá trị của biến bí mật ở bất kỳ đâu.
        context = replace_secret_values(context, self._current_secret_map(), REDACTED)
        self._show_resp_tab("ai")
        provider_label = "Ollama local" if provider == "ollama" else "OpenAI"
        model_label = model or "auto model"
        self._write_ai_analysis(f"  {provider_label} is analyzing the response ({model_label})...", "dim")
        self.ai_analyze_btn.config(state="disabled", text="Analyzing...")
        tab._status_lbl.config(text=f"AI đang phân tích response bằng {provider_label}...", fg=TEXT_DIM)

        def worker():
            try:
                if provider == "ollama":
                    result, model_used = analyze_response_with_ollama(context, model, credential)
                    result = f"[Ollama local: {model_used}]\n\n{result}"
                else:
                    result = analyze_response_with_ai(credential, context, model)
                    result = f"[OpenAI: {model}]\n\n{result}"
                self._ui.post(lambda result=result: self._finish_ai_analysis(tab, result, None))
            except Exception as e:
                error_msg = str(e) or repr(e) or e.__class__.__name__
                self._ui.post(lambda error_msg=error_msg: self._finish_ai_analysis(tab, "", error_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_ai_analysis(self, tab, result: str, error: str | None):
        self.ai_analyze_btn.config(state="normal", text="AI Analyze")
        if tab not in self.tabs:
            return
        if error:
            if error == "None":
                error = "Unknown OpenAI API error. Please try again; the next run will include HTTP details."
            tab.ai_analysis = f"AI analysis failed:\n{error}"
            tab._status_lbl.config(text=f"AI analysis failed: {error[:70]}", fg=RED_C)
            if self._is_active_tab(tab):
                self._show_resp_tab("ai")
                self._write_ai_analysis(tab.ai_analysis, "err")
            return

        tab.ai_analysis = result
        tab._status_lbl.config(text="AI analysis complete", fg=GREEN)
        if self._is_active_tab(tab):
            self._show_resp_tab("ai")
            self._write_ai_analysis(result)

    def _show_error(self, tab, msg):
        if tab not in self.tabs:
            return
        tab._send_btn.config(state="normal", text="▶  SEND REQUEST")
        tab._status_lbl.config(text=f"❌ {msg[:80]}", fg=RED_C)
        if not self._is_active_tab(tab):
            return
        self.status_badge.config(text="ERROR", bg=RED_C, fg=STATUS_TEXT)
        self._write_body(f"[LỖI]\n{msg}", "text/plain")
        self._schedule_response_search()

    def _copy_response(self):
        try:
            c = self.body_tw.get("1.0","end").strip()
            if c:
                self.clipboard_clear(); self.clipboard_append(c)
                if self.active_tab_idx >= 0:
                    self.tabs[self.active_tab_idx]._status_lbl.config(
                        text="✓ Đã copy response body", fg=GREEN)
        except: pass

    def _save_response(self):
        if self.active_tab_idx < 0: return
        tab = self.tabs[self.active_tab_idx]
        if tab.response is None:
            messagebox.showinfo("","Hãy gửi request trước."); return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON","*.json"),("Text","*.txt"),("All","*.*")])
        if path:
            with open(path,"wb") as f: f.write(tab.response.content)
            tab._status_lbl.config(text=f"✓ Đã lưu → {Path(path).name}", fg=GREEN)

    # ── Shared helpers ────────────────────────
    def _sec(self, parent, text, side="top"):
        lbl = tk.Label(parent, text=text, font=self.fn_badge, bg=BG, fg=TEXT_DIM)
        if side=="top": lbl.pack(anchor="w", pady=(0,4))
        else:           lbl.pack(side=side, padx=(0,8))

    def _mkbtn(self, parent, text, cmd, side="left", pad=(0,0)):
        b = tk.Button(parent, text=text, font=self.fn_label,
                      bg=BG3, fg=TEXT, activebackground=SURFACE_HOVER,
                      activeforeground=TEXT,
                      relief="flat", cursor="hand2",
                      padx=10, pady=4, command=cmd, bd=0)
        b.bind("<Enter>", lambda _e: b.config(bg=SURFACE_HOVER) if str(b["state"]) == "normal" else None)
        b.bind("<Leave>", lambda _e: b.config(bg=BG3) if str(b["state"]) == "normal" else None)
        b.pack(side=side, padx=pad)
        return b

    def _open_compare(self):
        """Mở popup so sánh curl. Seed từ các tab đang mở nếu có."""
        open_curls = []
        for tab in self.tabs:
            if hasattr(tab,"_curl_tw"):
                curl = tab._curl_tw.get("1.0","end").strip()
                if curl and not getattr(tab,"_ph_active",False):
                    open_curls.append(curl)
        # Đảm bảo ít nhất 2 slot
        while len(open_curls) < 2:
            open_curls.append("")
        CurlCompareWindow(self, initial_curls=open_curls)

    def _open_converter(self):
        """Mở popup convert String / JSON."""
        seed = ""
        if self.active_tab_idx >= 0:
            tab = self.tabs[self.active_tab_idx]
            seed = getattr(tab, "body_text", "") or ""
            if not seed and hasattr(tab, "_body_builder_tw") and tab._body_builder_tw:
                seed = tab._body_builder_tw.get("1.0", "end-1c")
        ConverterWindow(self, initial_text=seed)

    def _open_scenario(self):
        """Mở API Scenario runner."""
        ScenarioWindow(self)

    def _open_font_settings(self) -> None:
        """Mở dialog chọn font hệ thống, apply realtime cho toàn bộ UI."""
        win = tk.Toplevel(self)
        win.title("🔤 Font Settings")
        win.configure(bg=BG)
        win.geometry("540x720")
        win.minsize(480, 620)
        win.grab_set()

        # ── Header (top, fixed)
        hdr = tk.Frame(win, bg=TITLEBAR_BG, height=52)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🔤  Font Settings",
                 font=tkfont.Font(family=FONT_FAMILY, size=13, weight="bold"),
                 bg=TITLEBAR_BG, fg=TEXT).pack(side="left", padx=16, pady=12)

        # ── Button row (bottom, fixed) — must pack BEFORE body
        btn_row = tk.Frame(win, bg=BG2, padx=20, pady=12)
        btn_row.pack(fill="x", side="bottom")

        # ── Separator above buttons
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", side="bottom")

        # ── Scrollable body (middle, expands)
        canvas = tk.Canvas(win, bg=BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(win, orient="vertical", command=canvas.yview,
                                 bg=BG3, troughcolor=BG2, bd=0)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=BG, padx=20, pady=14)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")

        def _on_body_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(body_window, width=e.width)
        body.bind("<Configure>", _on_body_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse wheel scroll
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ── Get all system fonts
        all_fonts = sorted(set(tkfont.families()))
        # Separate mono fonts (heuristic: name contains common mono keywords)
        mono_keywords = {"mono","code","console","courier","terminal",
                         "cascadia","consolas","jetbrains","fira","hack",
                         "source code","inconsolata","menlo","monaco","roboto mono"}
        mono_fonts  = [f for f in all_fonts
                       if any(k in f.lower() for k in mono_keywords)]
        ui_fonts    = all_fonts  # show all for UI font

        # ── Section: UI font
        def section(text):
            f = tk.Frame(body, bg=BG)
            f.pack(fill="x", pady=(10,4))
            tk.Label(f, text=text, font=tkfont.Font(family=FONT_FAMILY, size=8, weight="bold"),
                     bg=BG, fg=TEXT_DIM).pack(anchor="w")
            tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(0,6))

        section("UI FONT  (labels, buttons, menus)")

        ui_var = tk.StringVar(value=self.fn_label.actual("family"))
        ui_size_var = tk.IntVar(value=self.fn_label.actual("size"))

        ui_row = tk.Frame(body, bg=BG)
        ui_row.pack(fill="x", pady=(0,4))

        # Font list with search
        ui_search_var = tk.StringVar()
        ui_search = tk.Entry(ui_row, textvariable=ui_search_var,
                             font=tkfont.Font(family=FONT_FAMILY, size=9),
                             bg=BG3, fg=TEXT, insertbackground=ACCENT,
                             relief="flat", bd=0)
        ui_search.pack(fill="x", ipady=5, padx=1, pady=(0,4))
        ui_search.insert(0, "🔍 Tìm font...")

        ui_list_frame = tk.Frame(ui_row, bg=BORDER)
        ui_list_frame.pack(fill="x")
        ui_sb = tk.Scrollbar(ui_list_frame, bg=BG3, troughcolor=BG2, bd=0)
        ui_sb.pack(side="right", fill="y")
        ui_listbox = tk.Listbox(ui_list_frame, bg=BG2, fg=TEXT,
                                font=tkfont.Font(family=FONT_FAMILY, size=9),
                                selectbackground=SURFACE_ACTIVE, selectforeground=ACTIVE_TEXT,
                                relief="flat", bd=0, height=8, activestyle="none",
                                yscrollcommand=ui_sb.set)
        ui_listbox.pack(fill="x", padx=1, pady=1)
        ui_sb.config(command=ui_listbox.yview)

        def populate_ui_list(q=""):
            ui_listbox.delete(0, "end")
            q_low = q.lower()
            for f in ui_fonts:
                if not q_low or q_low in f.lower():
                    ui_listbox.insert("end", f"  {f}")
            # Select current
            for i in range(ui_listbox.size()):
                if ui_var.get() in ui_listbox.get(i):
                    ui_listbox.selection_set(i)
                    ui_listbox.see(i)
                    break

        def on_ui_search_focus(focused):
            if focused and ui_search_var.get() == "🔍 Tìm font...":
                ui_search.delete(0, "end")
                ui_search.config(fg=TEXT)
            elif not focused and not ui_search_var.get():
                ui_search.insert(0, "🔍 Tìm font...")
                ui_search.config(fg=TEXT_DIM)

        ui_search.bind("<FocusIn>",    lambda e: on_ui_search_focus(True))
        ui_search.bind("<FocusOut>",   lambda e: on_ui_search_focus(False))
        ui_search.bind("<KeyRelease>", lambda e: populate_ui_list(
            "" if ui_search_var.get() == "🔍 Tìm font..." else ui_search_var.get()))

        def on_ui_select(e=None):
            sel = ui_listbox.curselection()
            if sel:
                ui_var.set(ui_listbox.get(sel[0]).strip())
                _update_preview()

        ui_listbox.bind("<<ListboxSelect>>", on_ui_select)
        populate_ui_list()

        # Size slider for UI font
        sz_row = tk.Frame(body, bg=BG)
        sz_row.pack(fill="x", pady=(6,0))
        tk.Label(sz_row, text="Cỡ chữ UI:", font=tkfont.Font(family=FONT_FAMILY, size=9),
                 bg=BG, fg=TEXT_DIM).pack(side="left")
        ui_size_lbl = tk.Label(sz_row, text=str(ui_size_var.get()),
                                font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
                                bg=BG, fg=ACCENT, width=3)
        ui_size_lbl.pack(side="right")
        ui_size_slider = tk.Scale(sz_row, from_=7, to=14, orient="horizontal",
                                   variable=ui_size_var, bg=BG, fg=TEXT,
                                   troughcolor=BG3, highlightthickness=0,
                                   activebackground=ACCENT, bd=0, showvalue=False,
                                   command=lambda v: (ui_size_lbl.config(text=v), _update_preview()))
        ui_size_slider.pack(side="left", fill="x", expand=True, padx=(8,8))

        # ── Section: Mono font
        section("MONO FONT  (curl input, response body, code)")

        mono_var = tk.StringVar(value=self.fn_mono.actual("family"))
        mono_size_var = tk.IntVar(value=self.fn_mono.actual("size"))

        mono_row = tk.Frame(body, bg=BG)
        mono_row.pack(fill="x", pady=(0,4))

        mono_search_var = tk.StringVar()
        mono_search = tk.Entry(mono_row, textvariable=mono_search_var,
                               font=tkfont.Font(family=FONT_FAMILY, size=9),
                               bg=BG3, fg=TEXT, insertbackground=ACCENT,
                               relief="flat", bd=0)
        mono_search.pack(fill="x", ipady=5, padx=1, pady=(0,4))
        mono_search.insert(0, "🔍 Tìm mono font...")

        mono_list_frame = tk.Frame(mono_row, bg=BORDER)
        mono_list_frame.pack(fill="x")
        mono_sb = tk.Scrollbar(mono_list_frame, bg=BG3, troughcolor=BG2, bd=0)
        mono_sb.pack(side="right", fill="y")
        mono_listbox = tk.Listbox(mono_list_frame, bg=BG2, fg=TEXT,
                                  font=tkfont.Font(family=FONT_FAMILY, size=9),
                                  selectbackground=SURFACE_ACTIVE, selectforeground=ACTIVE_TEXT,
                                  relief="flat", bd=0, height=6, activestyle="none",
                                  yscrollcommand=mono_sb.set)
        mono_listbox.pack(fill="x", padx=1, pady=1)
        mono_sb.config(command=mono_listbox.yview)

        def populate_mono_list(q=""):
            mono_listbox.delete(0, "end")
            q_low = q.lower()
            # Show mono fonts first, then all if no match
            pool = mono_fonts if mono_fonts else all_fonts
            full_pool = all_fonts
            shown = [f for f in pool if not q_low or q_low in f.lower()]
            if not shown:
                shown = [f for f in full_pool if not q_low or q_low in f.lower()]
            for f in shown:
                mono_listbox.insert("end", f"  {f}")
            for i in range(mono_listbox.size()):
                if mono_var.get() in mono_listbox.get(i):
                    mono_listbox.selection_set(i)
                    mono_listbox.see(i)
                    break

        def on_mono_search_focus(focused):
            if focused and mono_search_var.get() == "🔍 Tìm mono font...":
                mono_search.delete(0, "end")
                mono_search.config(fg=TEXT)
            elif not focused and not mono_search_var.get():
                mono_search.insert(0, "🔍 Tìm mono font...")
                mono_search.config(fg=TEXT_DIM)

        mono_search.bind("<FocusIn>",    lambda e: on_mono_search_focus(True))
        mono_search.bind("<FocusOut>",   lambda e: on_mono_search_focus(False))
        mono_search.bind("<KeyRelease>", lambda e: populate_mono_list(
            "" if mono_search_var.get() == "🔍 Tìm mono font..." else mono_search_var.get()))

        def on_mono_select(e=None):
            sel = mono_listbox.curselection()
            if sel:
                mono_var.set(mono_listbox.get(sel[0]).strip())
                _update_preview()

        mono_listbox.bind("<<ListboxSelect>>", on_mono_select)
        populate_mono_list()

        mono_sz_row = tk.Frame(body, bg=BG)
        mono_sz_row.pack(fill="x", pady=(6,0))
        tk.Label(mono_sz_row, text="Cỡ chữ Mono:", font=tkfont.Font(family=FONT_FAMILY, size=9),
                 bg=BG, fg=TEXT_DIM).pack(side="left")
        mono_size_lbl = tk.Label(mono_sz_row, text=str(mono_size_var.get()),
                                  font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
                                  bg=BG, fg=ACCENT, width=3)
        mono_size_lbl.pack(side="right")
        mono_size_slider = tk.Scale(mono_sz_row, from_=8, to=16, orient="horizontal",
                                     variable=mono_size_var, bg=BG, fg=TEXT,
                                     troughcolor=BG3, highlightthickness=0,
                                     activebackground=ACCENT, bd=0, showvalue=False,
                                     command=lambda v: (mono_size_lbl.config(text=v), _update_preview()))
        mono_size_slider.pack(side="left", fill="x", expand=True, padx=(8,8))

        # ── Preview
        section("PREVIEW")
        prev_frame = tk.Frame(body, bg=BG2, padx=12, pady=10)
        prev_frame.pack(fill="x")
        prev_ui = tk.Label(prev_frame,
                           text="The quick brown fox — Curl Runner UI Text",
                           bg=BG2, fg=TEXT, anchor="w")
        prev_ui.pack(fill="x", pady=(0,4))
        prev_mono = tk.Label(prev_frame,
                             text="curl -X POST https://api.example.com/login",
                             bg=BG2, fg=CYAN_C, anchor="w")
        prev_mono.pack(fill="x")

        def _update_preview():
            try:
                prev_ui.config(font=tkfont.Font(
                    family=ui_var.get(), size=ui_size_var.get()))
                prev_mono.config(font=tkfont.Font(
                    family=mono_var.get(), size=mono_size_var.get()))
            except Exception:
                pass

        _update_preview()

        # ── Wire up buttons (btn_row was created before body above)
        def _apply():
            """Apply font changes to all existing Font objects — realtime."""
            try:
                # Update UI fonts
                for fn_obj, size, weight in [
                    (self.fn_title, 14,  "bold"),
                    (self.fn_label, ui_size_var.get(), "normal"),
                    (self.fn_btn,   ui_size_var.get(), "bold"),
                    (self.fn_stat,  12,  "bold"),
                    (self.fn_badge, max(7, ui_size_var.get()-1), "bold"),
                    (self.fn_small, max(7, ui_size_var.get()-1), "normal"),
                    (self.fn_tab,   ui_size_var.get(), "normal"),
                ]:
                    fn_obj.configure(family=ui_var.get(), size=size, weight=weight)

                # Update mono fonts
                for fn_obj, size in [
                    (self.fn_mono,  mono_size_var.get()),
                    (self.fn_monos, max(8, mono_size_var.get()-1)),
                ]:
                    fn_obj.configure(family=mono_var.get(), size=size)

                # Persist to store
                store.save(store.DATA_DIR / "font_settings.json", {
                    "ui_family":    ui_var.get(),
                    "ui_size":      ui_size_var.get(),
                    "mono_family":  mono_var.get(),
                    "mono_size":    mono_size_var.get(),
                })

                self._show_font_applied_toast(ui_var.get(), mono_var.get())
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không apply được font:\n{e}", parent=win)

        def _reset():
            ui_var.set(FONT_FAMILY)
            mono_var.set(FONT_FAMILY_MONO)
            ui_size_var.set(9)
            mono_size_var.set(10)
            ui_size_lbl.config(text="9")
            mono_size_lbl.config(text="10")
            populate_ui_list(); populate_mono_list()
            _update_preview()

        tk.Button(btn_row, text="↺ Reset về mặc định",
                  font=tkfont.Font(family=FONT_FAMILY, size=9),
                  bg=BG3, fg=TEXT_DIM, activebackground=BORDER,
                  relief="flat", cursor="hand2", padx=12, pady=6,
                  command=_reset, bd=0).pack(side="left")

        tk.Button(btn_row, text="✓  Apply",
                  font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
                  bg=ACCENT, fg=ACTIVE_TEXT, activebackground=ACCENT2,
                  relief="flat", cursor="hand2", padx=20, pady=6,
                  command=_apply, bd=0).pack(side="right")

        tk.Button(btn_row, text="Apply & Đóng",
                  font=tkfont.Font(family=FONT_FAMILY, size=9),
                  bg=SURFACE_ACTIVE, fg=ACTIVE_TEXT, activebackground=ACCENT,
                  relief="flat", cursor="hand2", padx=14, pady=6,
                  command=lambda: (_apply(), win.destroy()), bd=0).pack(side="right", padx=(0,8))

    def _show_font_applied_toast(self, ui_font: str, mono_font: str) -> None:
        """Hiện toast notification nhỏ khi apply font thành công."""
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.configure(bg=SURFACE_ACTIVE)
        toast.attributes("-topmost", True)
        toast.attributes("-alpha", 0.95)

        tk.Label(toast,
                 text=f"✓  Font applied  —  UI: {ui_font[:20]}  ·  Mono: {mono_font[:20]}",
                 font=tkfont.Font(family=FONT_FAMILY, size=9),
                 bg=SURFACE_ACTIVE, fg=ACTIVE_TEXT, padx=16, pady=8).pack()

        # Position bottom-right of main window
        self.update_idletasks()
        wx = self.winfo_x() + self.winfo_width()  - 460
        wy = self.winfo_y() + self.winfo_height() - 60
        toast.geometry(f"+{wx}+{wy}")

        # Auto-dismiss after 2.5s with fade
        def _fade(alpha=0.95):
            if alpha > 0:
                toast.attributes("-alpha", alpha)
                toast.after(60, lambda: _fade(round(alpha - 0.08, 2)))
            else:
                toast.destroy()
        toast.after(2000, _fade)

    def _load_font_settings(self) -> None:
        """Load font settings đã lưu khi khởi động app."""
        try:
            settings = store.load(store.DATA_DIR / "font_settings.json", {})
            if not settings:
                return
            ui_fam   = settings.get("ui_family",   FONT_FAMILY)
            ui_sz    = settings.get("ui_size",      9)
            mono_fam = settings.get("mono_family",  FONT_FAMILY_MONO)
            mono_sz  = settings.get("mono_size",    10)

            for fn_obj, size, weight in [
                (self.fn_title, 14,  "bold"),
                (self.fn_label, ui_sz, "normal"),
                (self.fn_btn,   ui_sz, "bold"),
                (self.fn_stat,  12,   "bold"),
                (self.fn_badge, max(7, ui_sz-1), "bold"),
                (self.fn_small, max(7, ui_sz-1), "normal"),
                (self.fn_tab,   ui_sz, "normal"),
            ]:
                fn_obj.configure(family=ui_fam, size=size, weight=weight)

            for fn_obj, size in [
                (self.fn_mono,  mono_sz),
                (self.fn_monos, max(8, mono_sz-1)),
            ]:
                fn_obj.configure(family=mono_fam, size=size)
        except Exception:
            pass  # Fail silently — use default fonts

    def _chk(self, parent, text, var):
        tk.Checkbutton(parent, text=text, variable=var,
                       font=self.fn_label, bg=BG, fg=TEXT_DIM,
                       activebackground=BG, selectcolor=BG3,
                       activeforeground=TEXT, cursor="hand2",
                       relief="flat", bd=0).pack(side="left", padx=(0,8))
