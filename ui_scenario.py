# ui_scenario.py - API Scenario runner: sequential groups, parallel steps
# type: ignore
from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, font as tkfont
from typing import TYPE_CHECKING, Any

from constants import (
    BG, BG2, BG3, BORDER, ACCENT, TEXT, TEXT_DIM,
    ACTIVE_TEXT,
    GREEN, RED_C, YELLOW_C,
    SURFACE_HOVER, SURFACE_ACTIVE, TITLEBAR_BG, FONT_FAMILY, FONT_FAMILY_MONO,
)
from core import apply_env, parse_curl, execute_request, decode_response
import store
from scenario_report import build_scenario_report, export_scenario_report
from ui_theme import apply_modern_theme

if TYPE_CHECKING:
    from app import CurlRunnerApp


class ScenarioWindow(tk.Toplevel):
    """Run saved API workflows as sequential groups with parallel steps."""

    def __init__(self, parent: "CurlRunnerApp"):
        super().__init__(parent)
        self.parent_app = parent
        self.title("API Scenario")
        self.geometry("1320x820")
        self.minsize(980, 620)
        self.configure(bg=BG)
        apply_modern_theme(self)

        self.scenarios: list[dict] = store.load_scenarios()
        self.active_idx = 0
        self.selected_step_id: str | None = None
        self.step_results: dict[str, dict] = {}
        self.stop_event = threading.Event()
        self.running = False

        self._setup_fonts()
        self._ensure_default_scenario()
        self._build_ui()
        self._refresh_scenario_list()
        self._load_scenario(0)

    def _setup_fonts(self) -> None:
        self.fn_mono  = tkfont.Font(family=FONT_FAMILY_MONO, size=10)
        self.fn_monos = tkfont.Font(family=FONT_FAMILY_MONO, size=9)
        self.fn_label = tkfont.Font(family=FONT_FAMILY, size=9)
        self.fn_btn   = tkfont.Font(family=FONT_FAMILY, size=9, weight="bold")
        self.fn_badge = tkfont.Font(family=FONT_FAMILY, size=8, weight="bold")
        self.fn_small = tkfont.Font(family=FONT_FAMILY, size=8)
        self.fn_title = tkfont.Font(family=FONT_FAMILY, size=13, weight="bold")

    def _ensure_default_scenario(self) -> None:
        if self.scenarios:
            return
        self.scenarios.append({
            "id": str(uuid.uuid4())[:8],
            "name": "New Scenario",
            "steps": [],
        })
        store.save_scenarios(self.scenarios)

    def _build_ui(self) -> None:
        tb = tk.Frame(self, bg=TITLEBAR_BG, height=52)
        tb.pack(fill="x", side="top")
        tb.pack_propagate(False)
        tk.Label(tb, text="API Scenario", font=self.fn_title,
                 bg=TITLEBAR_BG, fg=TEXT).pack(side="left", padx=14, pady=10)
        self._mkbtn(tb, "New", self._new_scenario, side="left", pad=(8, 0))
        self._mkbtn(tb, "Save", self._save_active, side="left", pad=(6, 0))
        self._mkbtn(tb, "Rename", self._rename_scenario, side="left", pad=(6, 0))
        self._mkbtn(tb, "Delete", self._delete_scenario, side="left", pad=(6, 0))
        self.run_btn = self._mkbtn(tb, "Run Scenario", self._run_scenario, side="right", pad=(0, 12))
        self.stop_btn = self._mkbtn(tb, "Stop", self._stop_run, side="right", pad=(0, 6))
        self.stop_btn.config(state="disabled")
        self.export_btn = self._mkbtn(tb, "Export Report", self._show_export_menu, side="right", pad=(0, 6))

        main = tk.PanedWindow(self, orient="horizontal", bg=BORDER,
                              sashwidth=5, sashrelief="flat", bd=0)
        main.pack(fill="both", expand=True, padx=8, pady=8)

        left = tk.Frame(main, bg=BG)
        main.add(left, width=250, minsize=200)
        tk.Label(left, text="SCENARIOS", font=self.fn_badge,
                 bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 4))
        lb_wrap = tk.Frame(left, bg=BORDER)
        lb_wrap.pack(fill="both", expand=True)
        sb = tk.Scrollbar(lb_wrap, bg=BG3, troughcolor=BG2, bd=0)
        sb.pack(side="right", fill="y")
        self.scenario_list = tk.Listbox(
            lb_wrap, bg=BG2, fg=TEXT, font=self.fn_label,
            selectbackground=ACCENT, selectforeground=ACTIVE_TEXT,
            relief="flat", bd=0, activestyle="none", yscrollcommand=sb.set
        )
        self.scenario_list.pack(fill="both", expand=True, padx=1, pady=1)
        sb.config(command=self.scenario_list.yview)
        self.scenario_list.bind("<<ListboxSelect>>", self._on_scenario_select)

        right = tk.Frame(main, bg=BG)
        main.add(right, minsize=650)

        controls = tk.Frame(right, bg=BG)
        controls.pack(fill="x", pady=(0, 6))
        self._mkbtn(controls, "Add Step", self._add_step, side="left")
        self._mkbtn(controls, "Update Step", self._update_step, side="left", pad=(6, 0))
        self._mkbtn(controls, "Duplicate", self._duplicate_step, side="left", pad=(6, 0))
        self._mkbtn(controls, "Delete Step", self._delete_step, side="left", pad=(6, 0))
        self._mkbtn(controls, "Up", lambda: self._move_step(-1), side="left", pad=(10, 0))
        self._mkbtn(controls, "Down", lambda: self._move_step(1), side="left", pad=(6, 0))
        self._mkbtn(controls, "Import Open Tabs", self._import_open_tabs, side="right")
        self.stop_on_fail_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            controls, text="Stop on fail", variable=self.stop_on_fail_var,
            font=self.fn_label, bg=BG, fg=TEXT_DIM,
            activebackground=BG, activeforeground=TEXT,
            selectcolor=BG3, cursor="hand2", bd=0
        ).pack(side="right", padx=(0, 12))

        self.summary_lbl = tk.Label(right, text="", font=self.fn_small,
                                    bg=BG, fg=TEXT_DIM, anchor="w")
        self.summary_lbl.pack(fill="x", pady=(0, 4))

        tree_wrap = tk.Frame(right, bg=BORDER)
        tree_wrap.pack(fill="both", expand=True)
        style = ttk.Style()
        style.configure(
            "Treeview", background=BG2, foreground=TEXT,
            fieldbackground=BG2, font=(FONT_FAMILY, 9),
            rowheight=30, borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", SURFACE_ACTIVE)],
            foreground=[("selected", ACTIVE_TEXT)],
        )
        cols = ("order", "group", "enabled", "name", "method", "url", "status", "time")
        self.step_tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", height=10)
        headings = {
            "order": "#", "group": "Group", "enabled": "On", "name": "Step",
            "method": "Method", "url": "URL", "status": "Status", "time": "Time",
        }
        widths = {
            "order": 42, "group": 64, "enabled": 50, "name": 170,
            "method": 80, "url": 360, "status": 115, "time": 80,
        }
        for col in cols:
            self.step_tree.heading(col, text=headings[col])
            self.step_tree.column(col, width=widths[col], anchor="w", stretch=(col in ("name", "url")))
        ysb = tk.Scrollbar(tree_wrap, command=self.step_tree.yview, bg=BG3, troughcolor=BG2, bd=0)
        self.step_tree.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.step_tree.pack(fill="both", expand=True, padx=1, pady=1)
        self.step_tree.bind("<<TreeviewSelect>>", self._on_step_select)
        self.step_tree.tag_configure("ok", foreground=GREEN)
        self.step_tree.tag_configure("err", foreground=RED_C)
        self.step_tree.tag_configure("run", foreground=YELLOW_C)
        self.step_tree.tag_configure("skip", foreground=TEXT_DIM)

        editor = tk.Frame(right, bg=BG2)
        editor.pack(fill="both", pady=(8, 0))
        meta = tk.Frame(editor, bg=BG2)
        meta.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(meta, text="Name:", font=self.fn_label, bg=BG2, fg=TEXT_DIM).pack(side="left")
        self.step_name_var = tk.StringVar()
        tk.Entry(meta, textvariable=self.step_name_var, font=self.fn_label,
                 bg=BG3, fg=TEXT, insertbackground=ACCENT,
                 relief="flat", bd=0, width=24).pack(side="left", padx=(4, 10), ipady=3)
        tk.Label(meta, text="Group:", font=self.fn_label, bg=BG2, fg=TEXT_DIM).pack(side="left")
        self.step_group_var = tk.StringVar(value="1")
        tk.Entry(meta, textvariable=self.step_group_var, font=self.fn_monos,
                 bg=BG3, fg=TEXT, insertbackground=ACCENT,
                 relief="flat", bd=0, width=6).pack(side="left", padx=(4, 10), ipady=3)
        self.step_enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            meta, text="Enabled", variable=self.step_enabled_var,
            font=self.fn_label, bg=BG2, fg=TEXT_DIM,
            activebackground=BG2, activeforeground=TEXT,
            selectcolor=BG3, cursor="hand2", bd=0
        ).pack(side="left")
        tk.Label(meta, text="Steps with the same Group run in parallel; groups run sequentially.",
                 font=self.fn_small, bg=BG2, fg=TEXT_DIM).pack(side="right")

        curl_wrap = tk.Frame(editor, bg=BORDER)
        curl_wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.step_curl_tw = tk.Text(
            curl_wrap, bg=BG2, fg=TEXT, insertbackground=ACCENT,
            font=self.fn_mono, wrap="word", relief="flat",
            padx=10, pady=8, selectbackground=ACCENT,
            selectforeground=ACTIVE_TEXT, undo=True, bd=0, height=7
        )
        curl_sb = tk.Scrollbar(curl_wrap, command=self.step_curl_tw.yview,
                               bg=BG3, troughcolor=BG2, bd=0)
        self.step_curl_tw.configure(yscrollcommand=curl_sb.set)
        curl_sb.pack(side="right", fill="y")
        self.step_curl_tw.pack(fill="both", expand=True, padx=1, pady=1)

        qa = tk.PanedWindow(editor, orient="horizontal", bg=BORDER,
                            sashwidth=5, sashrelief="flat", bd=0)
        qa.pack(fill="both", padx=8, pady=(0, 8))
        extract_frame = self._build_rule_panel(
            qa,
            "EXTRACTORS",
            "token = json:$.data.token\nrequest_id = header:X-Request-Id",
        )
        assert_frame = self._build_rule_panel(
            qa,
            "ASSERTIONS",
            "status == 200\nbody contains success\njson $.ok == true",
        )
        qa.add(extract_frame, minsize=280)
        qa.add(assert_frame, minsize=280)

        log_wrap = tk.Frame(right, bg=BORDER)
        log_wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.log_tw = tk.Text(
            log_wrap, bg=BG2, fg=TEXT, font=self.fn_monos,
            wrap="word", relief="flat", padx=10, pady=8,
            selectbackground=ACCENT, selectforeground=ACTIVE_TEXT,
            state="disabled", bd=0, height=7
        )
        log_sb = tk.Scrollbar(log_wrap, command=self.log_tw.yview,
                              bg=BG3, troughcolor=BG2, bd=0)
        self.log_tw.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self.log_tw.pack(fill="both", expand=True, padx=1, pady=1)
        self.log_tw.tag_configure("ok", foreground=GREEN)
        self.log_tw.tag_configure("err", foreground=RED_C)
        self.log_tw.tag_configure("run", foreground=YELLOW_C)
        self.log_tw.tag_configure("dim", foreground=TEXT_DIM)

    def _build_rule_panel(self, parent: tk.Widget, title: str, placeholder: str) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG2)
        hdr = tk.Frame(frame, bg=BG2)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title, font=self.fn_badge,
                 bg=BG2, fg=TEXT_DIM).pack(side="left", padx=8, pady=(6, 2))
        tk.Label(hdr, text="one rule per line", font=self.fn_small,
                 bg=BG2, fg=TEXT_DIM).pack(side="right", padx=8, pady=(6, 2))
        wrap = tk.Frame(frame, bg=BORDER)
        wrap.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        tw = tk.Text(
            wrap, bg=BG2, fg=TEXT, insertbackground=ACCENT,
            font=self.fn_monos, wrap="word", relief="flat",
            padx=8, pady=6, selectbackground=ACCENT,
            selectforeground=ACTIVE_TEXT, undo=True, bd=0, height=5
        )
        sb = tk.Scrollbar(wrap, command=tw.yview, bg=BG3, troughcolor=BG2, bd=0)
        tw.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tw.pack(fill="both", expand=True)
        if title == "EXTRACTORS":
            self.extract_tw = tw
        else:
            self.assert_tw = tw
        tw.insert("1.0", placeholder)
        tw.config(fg=TEXT_DIM)
        tw.bind("<FocusIn>", lambda _e, w=tw, p=placeholder: self._clear_rule_placeholder(w, p))
        tw.bind("<FocusOut>", lambda _e, w=tw, p=placeholder: self._restore_rule_placeholder(w, p))
        return frame

    def _clear_rule_placeholder(self, tw: tk.Text, placeholder: str) -> None:
        if tw.get("1.0", "end").strip() == placeholder:
            tw.delete("1.0", "end")
            tw.config(fg=TEXT)

    def _restore_rule_placeholder(self, tw: tk.Text, placeholder: str) -> None:
        if not tw.get("1.0", "end").strip():
            tw.insert("1.0", placeholder)
            tw.config(fg=TEXT_DIM)

    def _rule_text(self, tw: tk.Text) -> str:
        text = tw.get("1.0", "end").strip()
        return "" if tw.cget("fg") == TEXT_DIM else text

    # Scenario management
    def _current_scenario(self) -> dict:
        return self.scenarios[self.active_idx]

    def _refresh_scenario_list(self) -> None:
        self.scenario_list.delete(0, "end")
        for sc in self.scenarios:
            self.scenario_list.insert("end", f"  {sc.get('name', 'Untitled')}")
        if self.scenarios:
            self.scenario_list.selection_clear(0, "end")
            self.scenario_list.selection_set(self.active_idx)
            self.scenario_list.activate(self.active_idx)

    def _on_scenario_select(self, _=None) -> None:
        sel = self.scenario_list.curselection()
        if not sel or sel[0] == self.active_idx:
            return
        if self.running:
            messagebox.showinfo("", "Scenario đang chạy. Hãy Stop trước khi đổi.")
            self._refresh_scenario_list()
            return
        self._save_current_editor()
        self._save_active(silent=True)
        self._load_scenario(sel[0])

    def _load_scenario(self, idx: int) -> None:
        self.active_idx = max(0, min(idx, len(self.scenarios) - 1))
        self.selected_step_id = None
        self.step_results = {}
        self._refresh_scenario_list()
        self._refresh_steps()
        self._clear_editor()
        self._clear_log()
        self._log("Chọn Run Scenario để chạy. Cùng Group sẽ chạy parallel.", "dim")

    def _new_scenario(self) -> None:
        if self.running:
            return
        name = simpledialog.askstring("New Scenario", "Tên scenario:", parent=self)
        if not name:
            return
        self._save_current_editor()
        self.scenarios.append({"id": str(uuid.uuid4())[:8], "name": name.strip(), "steps": []})
        self.active_idx = len(self.scenarios) - 1
        self._save_all()
        self._load_scenario(self.active_idx)

    def _rename_scenario(self) -> None:
        sc = self._current_scenario()
        name = simpledialog.askstring("Rename Scenario", "Tên mới:", initialvalue=sc.get("name", ""), parent=self)
        if not name:
            return
        sc["name"] = name.strip()
        self._save_all()
        self._refresh_scenario_list()

    def _delete_scenario(self) -> None:
        if len(self.scenarios) <= 1:
            messagebox.showinfo("", "Giữ ít nhất 1 scenario.")
            return
        sc = self._current_scenario()
        if not messagebox.askyesno("Delete Scenario", f"Xóa scenario '{sc.get('name')}'?"):
            return
        self.scenarios.pop(self.active_idx)
        self.active_idx = min(self.active_idx, len(self.scenarios) - 1)
        self._save_all()
        self._load_scenario(self.active_idx)

    def _save_all(self) -> None:
        store.save_scenarios(self.scenarios)

    def _save_active(self, silent: bool = False) -> None:
        self._save_current_editor()
        self._save_all()
        if not silent:
            self._log("Saved scenario.", "ok")

    # Step editing
    def _steps(self) -> list[dict]:
        sc = self._current_scenario()
        sc.setdefault("steps", [])
        return sc["steps"]

    def _new_step_dict(self, name: str = "New Step", curl: str = "", group: int = 1) -> dict:
        return {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "curl": curl,
            "group": group,
            "enabled": True,
            "extractors": "",
            "assertions": "",
        }

    def _add_step(self) -> None:
        steps = self._steps()
        group = self._next_group()
        step = self._new_step_dict(group=group)
        steps.append(step)
        self.selected_step_id = step["id"]
        self._save_all()
        self._refresh_steps()
        self._load_step_editor(step)

    def _duplicate_step(self) -> None:
        step = self._selected_step()
        if not step:
            return
        steps = self._steps()
        idx = steps.index(step)
        clone = dict(step)
        clone["id"] = str(uuid.uuid4())[:8]
        clone["name"] = f"{step.get('name', 'Step')} Copy"
        steps.insert(idx + 1, clone)
        self.selected_step_id = clone["id"]
        self._save_all()
        self._refresh_steps()
        self._load_step_editor(clone)

    def _delete_step(self) -> None:
        step = self._selected_step()
        if not step:
            return
        self._steps().remove(step)
        self.selected_step_id = None
        self._save_all()
        self._refresh_steps()
        self._clear_editor()

    def _move_step(self, direction: int) -> None:
        step = self._selected_step()
        if not step:
            return
        steps = self._steps()
        idx = steps.index(step)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(steps):
            return
        steps[idx], steps[new_idx] = steps[new_idx], steps[idx]
        self._save_all()
        self._refresh_steps()
        self._select_step(step["id"])

    def _update_step(self) -> None:
        if self._save_current_editor():
            self._save_all()
            self._refresh_steps()
            self._log("Updated step.", "ok")

    def _save_current_editor(self) -> bool:
        step = self._selected_step()
        if not step:
            return False
        name = self.step_name_var.get().strip() or "Unnamed Step"
        try:
            group = int(self.step_group_var.get().strip() or "1")
            if group < 1:
                raise ValueError
        except Exception:
            messagebox.showwarning("", "Group phải là số nguyên >= 1.")
            return False
        step["name"] = name
        step["group"] = group
        step["enabled"] = bool(self.step_enabled_var.get())
        step["curl"] = self.step_curl_tw.get("1.0", "end").strip()
        step["extractors"] = self._rule_text(self.extract_tw)
        step["assertions"] = self._rule_text(self.assert_tw)
        return True

    def _clear_editor(self) -> None:
        self.step_name_var.set("")
        self.step_group_var.set("1")
        self.step_enabled_var.set(True)
        self.step_curl_tw.delete("1.0", "end")
        self.extract_tw.delete("1.0", "end")
        self.assert_tw.delete("1.0", "end")
        self._restore_rule_placeholder(self.extract_tw, "token = json:$.data.token\nrequest_id = header:X-Request-Id")
        self._restore_rule_placeholder(self.assert_tw, "status == 200\nbody contains success\njson $.ok == true")

    def _load_step_editor(self, step: dict) -> None:
        self.selected_step_id = step.get("id")
        self.step_name_var.set(step.get("name", ""))
        self.step_group_var.set(str(step.get("group", 1)))
        self.step_enabled_var.set(bool(step.get("enabled", True)))
        self.step_curl_tw.delete("1.0", "end")
        self.step_curl_tw.insert("1.0", step.get("curl", ""))
        self.extract_tw.delete("1.0", "end")
        self.assert_tw.delete("1.0", "end")
        if step.get("extractors", "").strip():
            self.extract_tw.insert("1.0", step.get("extractors", ""))
            self.extract_tw.config(fg=TEXT)
        else:
            self._restore_rule_placeholder(self.extract_tw, "token = json:$.data.token\nrequest_id = header:X-Request-Id")
        if step.get("assertions", "").strip():
            self.assert_tw.insert("1.0", step.get("assertions", ""))
            self.assert_tw.config(fg=TEXT)
        else:
            self._restore_rule_placeholder(self.assert_tw, "status == 200\nbody contains success\njson $.ok == true")
        self._select_step(self.selected_step_id)

    def _on_step_select(self, _=None) -> None:
        sel = self.step_tree.selection()
        if not sel:
            return
        step_id = sel[0]
        if step_id == self.selected_step_id:
            return
        self._save_current_editor()
        step = self._step_by_id(step_id)
        if step:
            self._load_step_editor(step)

    def _selected_step(self) -> dict | None:
        return self._step_by_id(self.selected_step_id)

    def _step_by_id(self, step_id: str | None) -> dict | None:
        if not step_id:
            return None
        for step in self._steps():
            if step.get("id") == step_id:
                return step
        return None

    def _select_step(self, step_id: str | None) -> None:
        if not step_id:
            return
        if self.step_tree.exists(step_id):
            self.step_tree.selection_set(step_id)
            self.step_tree.focus(step_id)
            self.step_tree.see(step_id)

    def _next_group(self) -> int:
        groups = [self._safe_group(s) for s in self._steps()]
        return (max(groups) + 1) if groups else 1

    def _safe_group(self, step: dict) -> int:
        try:
            group = int(step.get("group", 1))
            return max(1, group)
        except Exception:
            return 1

    def _refresh_steps(self) -> None:
        for row in self.step_tree.get_children():
            self.step_tree.delete(row)
        steps = self._steps()
        for idx, step in enumerate(steps, start=1):
            parsed = self._preview_parse(step.get("curl", ""))
            result = self.step_results.get(step.get("id"), {})
            status = result.get("status", "")
            elapsed = result.get("elapsed", "")
            tag = result.get("tag", "skip" if not step.get("enabled", True) else "")
            self.step_tree.insert("", "end", iid=step.get("id"), values=(
                idx,
                self._safe_group(step),
                "yes" if step.get("enabled", True) else "no",
                step.get("name", ""),
                parsed.get("method", ""),
                parsed.get("url", ""),
                status,
                elapsed,
            ), tags=(tag,))
        self.summary_lbl.config(text=f"{len(steps)} step(s). Same Group = parallel. Group 1 runs before Group 2.")

    def _preview_parse(self, curl: str) -> dict:
        try:
            parsed = parse_curl(curl)
            return {"method": parsed.get("method", ""), "url": parsed.get("url", "")}
        except Exception:
            return {"method": "", "url": curl[:80] if curl else ""}

    def _import_open_tabs(self) -> None:
        added = 0
        steps = self._steps()
        next_group = self._next_group()
        for tab in self.parent_app.tabs:
            if not hasattr(tab, "_curl_tw") or getattr(tab, "_ph_active", False):
                continue
            curl = tab._curl_tw.get("1.0", "end").strip()
            if not curl:
                continue
            steps.append(self._new_step_dict(tab.name, curl, next_group))
            next_group += 1
            added += 1
        self._save_all()
        self._refresh_steps()
        self._log(f"Imported {added} open tab(s).", "ok" if added else "dim")

    # Extractors / assertions
    def _active_rule_lines(self, text: str) -> list[str]:
        out = []
        for line in (text or "").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
        return out

    def _extract_values(self, rules: str, resp, body_text: str) -> tuple[dict[str, str], list[str]]:
        extracted: dict[str, str] = {}
        logs: list[str] = []
        headers = {str(k).lower(): str(v) for k, v in dict(resp.headers).items()}
        body_json = None
        json_loaded = False

        for line in self._active_rule_lines(rules):
            m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(json|header|regex)\s*:(.+)$", line, re.I)
            if not m:
                raise ValueError(f"Extractor không hợp lệ: {line}")
            name, source, selector = m.group(1), m.group(2).lower(), m.group(3).strip()
            if source == "header":
                value = headers.get(selector.lower())
                if value is None:
                    raise ValueError(f"Extractor `{name}` không tìm thấy header `{selector}`")
            elif source == "regex":
                hit = re.search(selector, body_text, re.S)
                if not hit:
                    raise ValueError(f"Extractor `{name}` không match regex")
                value = hit.group(1) if hit.groups() else hit.group(0)
            else:
                if not json_loaded:
                    body_json = json.loads(body_text)
                    json_loaded = True
                value = self._json_path_get(body_json, selector)
            extracted[name] = str(value)
            logs.append(f"extract {name}={str(value)[:80]}")
        return extracted, logs

    def _evaluate_assertions(self, rules: str, resp, body_text: str) -> tuple[bool, list[str]]:
        lines = self._active_rule_lines(rules)
        if not lines:
            ok = 200 <= resp.status_code < 400
            return ok, [f"default status 2xx/3xx => {'PASS' if ok else 'FAIL'}"]

        details: list[str] = []
        body_json = None
        json_loaded = False
        headers = {str(k).lower(): str(v) for k, v in dict(resp.headers).items()}

        for line in lines:
            passed = False
            if m := re.match(r"^status\s*(==|!=|>=|<=|>|<)\s*(\d+)$", line, re.I):
                actual = int(resp.status_code)
                expected = int(m.group(2))
                passed = self._compare(actual, m.group(1), expected)
            elif m := re.match(r"^status\s+in\s+(.+)$", line, re.I):
                expected_codes = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
                passed = int(resp.status_code) in expected_codes
            elif m := re.match(r"^body\s+(contains|not_contains)\s+(.+)$", line, re.I):
                needle = self._strip_quotes(m.group(2).strip())
                contains = needle in body_text
                passed = contains if m.group(1).lower() == "contains" else not contains
            elif m := re.match(r"^header\s+([^\s]+)\s+(contains|==|!=)\s+(.+)$", line, re.I):
                actual = headers.get(m.group(1).lower(), "")
                expected = self._strip_quotes(m.group(3).strip())
                op = m.group(2).lower()
                passed = (expected in actual) if op == "contains" else self._compare(str(actual), op, expected)
            elif m := re.match(r"^json\s+(\S+)\s+exists$", line, re.I):
                if not json_loaded:
                    body_json = json.loads(body_text)
                    json_loaded = True
                self._json_path_get(body_json, m.group(1))
                passed = True
            elif m := re.match(r"^json\s+(\S+)\s*(==|!=|>=|<=|>|<)\s*(.+)$", line, re.I):
                if not json_loaded:
                    body_json = json.loads(body_text)
                    json_loaded = True
                actual = self._json_path_get(body_json, m.group(1))
                expected = self._coerce_value(self._strip_quotes(m.group(3).strip()))
                passed = self._compare(actual, m.group(2), expected)
            else:
                raise ValueError(f"Assertion không hợp lệ: {line}")
            details.append(f"{'PASS' if passed else 'FAIL'}: {line}")
            if not passed:
                return False, details
        return True, details

    def _json_path_get(self, data: Any, path: str) -> Any:
        if not path.startswith("$"):
            raise ValueError(f"JSON path phải bắt đầu bằng `$`: {path}")
        cur = data
        for key, idx in re.findall(r"\.([A-Za-z_][\w-]*)|\[(\d+)\]", path[1:]):
            if key:
                if not isinstance(cur, dict) or key not in cur:
                    raise ValueError(f"Không tìm thấy JSON path `{path}`")
                cur = cur[key]
            else:
                i = int(idx)
                if not isinstance(cur, list) or i >= len(cur):
                    raise ValueError(f"Không tìm thấy JSON path `{path}`")
                cur = cur[i]
        return cur

    def _strip_quotes(self, value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            return value[1:-1]
        return value

    def _coerce_value(self, value: str) -> Any:
        lower = value.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        if lower == "null":
            return None
        try:
            return int(value)
        except Exception:
            pass
        try:
            return float(value)
        except Exception:
            return value

    def _compare(self, actual: Any, op: str, expected: Any) -> bool:
        if op == "==":
            return actual == expected or str(actual) == str(expected)
        if op == "!=":
            return not self._compare(actual, "==", expected)
        try:
            left = float(actual)
            right = float(expected)
        except Exception:
            left = str(actual)
            right = str(expected)
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        return False

    # Report export
    def _show_export_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, bg=BG3, fg=TEXT, activebackground=ACCENT)
        menu.add_command(label="HTML Report", command=lambda: self._export_report("html"))
        menu.add_command(label="CSV Results", command=lambda: self._export_report("csv"))
        menu.add_command(label="JUnit XML", command=lambda: self._export_report("xml"))
        x = self.export_btn.winfo_rootx()
        y = self.export_btn.winfo_rooty() + self.export_btn.winfo_height()
        menu.tk_popup(x, y)

    def _export_report(self, extension: str) -> None:
        if self.running:
            messagebox.showinfo("Export Report", "Wait for the scenario run to finish before exporting.")
            return
        completed = [result for result in self.step_results.values() if result.get("ok") is not None]
        if not completed:
            messagebox.showinfo("Export Report", "Run the scenario before exporting a report.")
            return

        scenario = self._current_scenario()
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(scenario.get("name", "scenario"))).strip("-.")
        safe_name = safe_name or "scenario"
        file_types = {
            "html": [("HTML Report", "*.html")],
            "csv": [("CSV Results", "*.csv")],
            "xml": [("JUnit XML", "*.xml")],
        }
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export Scenario Report",
            initialfile=f"{safe_name}-report.{extension}",
            defaultextension=f".{extension}",
            filetypes=file_types[extension] + [("All files", "*.*")],
        )
        if not path:
            return

        try:
            report = build_scenario_report(
                scenario,
                self.step_results,
                environment=self.parent_app.active_env,
                summary=str(self.summary_lbl.cget("text")),
            )
            output = export_scenario_report(report, path)
        except Exception as exc:
            messagebox.showerror("Export Report", str(exc) or exc.__class__.__name__)
            return

        self._log(f"Exported {extension.upper()} report: {output.name}", "ok")
        messagebox.showinfo("Export Report", f"Report saved to:\n{output}")

    # Runner
    def _run_scenario(self) -> None:
        if self.running:
            return
        if not self._save_current_editor() and self.selected_step_id:
            return
        steps = [dict(s) for s in self._steps() if s.get("enabled", True) and s.get("curl", "").strip()]
        if not steps:
            messagebox.showinfo("", "Scenario chưa có step nào enabled/có curl.")
            return
        self._save_all()
        self.step_results = {}
        self._refresh_steps()
        self._clear_log()
        self.stop_event.clear()
        self.running = True
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.export_btn.config(state="disabled")

        runtime_env = dict(self.parent_app.environments.get(self.parent_app.active_env, {}))
        threading.Thread(target=self._run_worker, args=(steps, runtime_env), daemon=True).start()

    def _stop_run(self) -> None:
        self.stop_event.set()
        self._log("Stop requested. Running requests will finish, next groups will be skipped.", "err")

    def _run_worker(self, steps: list[dict], runtime_env: dict[str, str]) -> None:
        started = len(steps)
        passed = 0
        failed = 0
        grouped: dict[int, list[dict]] = {}
        for step in steps:
            grouped.setdefault(self._safe_group(step), []).append(step)

        try:
            for group in sorted(grouped):
                if self.stop_event.is_set():
                    break
                group_steps = grouped[group]
                self._after_log(f"Group {group}: running {len(group_steps)} step(s) in parallel.", "run")
                self._after_mark_group(group_steps, "RUNNING", "", "run")
                max_workers = max(1, min(len(group_steps), 16))
                group_extracts: dict[str, str] = {}
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(self._run_step, step, dict(runtime_env)): step
                        for step in group_steps
                    }
                    group_failed = False
                    for future in as_completed(futures):
                        step = futures[future]
                        result = future.result()
                        if result["ok"]:
                            passed += 1
                            group_extracts.update(result.get("extracts", {}))
                        else:
                            failed += 1
                            group_failed = True
                        self.after(0, lambda s=step, r=result: self._apply_step_result(s, r))
                if group_extracts:
                    runtime_env.update(group_extracts)
                    names = ", ".join(sorted(group_extracts))
                    self._after_log(f"Group {group}: extracted variables for next group: {names}", "ok")
                if group_failed and self.stop_on_fail_var.get():
                    self._after_log(f"Group {group}: failed, stopping scenario.", "err")
                    break
        finally:
            self.after(0, lambda: self._finish_run(started, passed, failed))

    def _run_step(self, step: dict, runtime_env: dict[str, str]) -> dict[str, Any]:
        name = step.get("name", "Step")
        try:
            curl = apply_env(step.get("curl", ""), runtime_env)
            parsed = parse_curl(curl)
            parsed["timeout"] = parsed.get("timeout", 30)
            resp, elapsed = execute_request(parsed)
            body_text, _ = decode_response(resp, True)
            extracts, extract_logs = self._extract_values(step.get("extractors", ""), resp, body_text)
            ok, assertion_logs = self._evaluate_assertions(step.get("assertions", ""), resp, body_text)
            detail = "; ".join(assertion_logs + extract_logs)
            suffix = f" · {detail}" if detail else ""
            return {
                "ok": ok,
                "status": f"{resp.status_code} {resp.reason}",
                "elapsed": f"{elapsed:.0f} ms",
                "elapsed_ms": float(elapsed),
                "tag": "ok" if ok else "err",
                "message": f"{name}: {resp.status_code} {resp.reason} · {elapsed:.0f} ms{suffix}",
                "extracts": extracts,
                "extract_names": sorted(extracts),
                "assertions": assertion_logs,
                "error": "",
            }
        except Exception as exc:
            msg = str(exc) or repr(exc) or exc.__class__.__name__
            return {
                "ok": False,
                "status": "ERROR",
                "elapsed": "",
                "elapsed_ms": 0.0,
                "tag": "err",
                "message": f"{name}: ERROR · {msg}",
                "extracts": {},
                "extract_names": [],
                "assertions": [],
                "error": msg,
            }

    def _after_mark_group(self, steps: list[dict], status: str, elapsed: str, tag: str) -> None:
        self.after(0, lambda: [self._set_step_result(s, status, elapsed, tag) for s in steps])

    def _apply_step_result(self, step: dict, result: dict) -> None:
        self._set_step_result(step, result["status"], result["elapsed"], result["tag"], result)
        self._log(result["message"], "ok" if result["ok"] else "err")

    def _set_step_result(
        self,
        step: dict,
        status: str,
        elapsed: str,
        tag: str,
        details: dict | None = None,
    ) -> None:
        step_id = step.get("id")
        result = dict(details or {})
        result.update({"status": status, "elapsed": elapsed, "tag": tag})
        self.step_results[step_id] = result
        if not self.step_tree.exists(step_id):
            return
        values = list(self.step_tree.item(step_id, "values"))
        values[6] = status
        values[7] = elapsed
        self.step_tree.item(step_id, values=values, tags=(tag,))

    def _finish_run(self, started: int, passed: int, failed: int) -> None:
        self.running = False
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.export_btn.config(state="normal")
        stopped = " · stopped" if self.stop_event.is_set() else ""
        summary = f"Scenario complete: {passed} passed, {failed} failed, {started} total{stopped}."
        self.summary_lbl.config(text=summary)
        self._log(summary, "ok" if failed == 0 else "err")

    # Log / widgets
    def _clear_log(self) -> None:
        self.log_tw.config(state="normal")
        self.log_tw.delete("1.0", "end")
        self.log_tw.config(state="disabled")

    def _after_log(self, text: str, tag: str = "dim") -> None:
        self.after(0, lambda: self._log(text, tag))

    def _log(self, text: str, tag: str = "dim") -> None:
        self.log_tw.config(state="normal")
        self.log_tw.insert("end", f"{text}\n", tag)
        self.log_tw.see("end")
        self.log_tw.config(state="disabled")

    def _mkbtn(self, parent: tk.Widget, text: str, cmd, side: str = "left", pad=(0, 0)):
        b = tk.Button(parent, text=text, font=self.fn_label,
                      bg=BG3, fg=TEXT, activebackground=SURFACE_HOVER,
                      activeforeground=TEXT,
                      relief="flat", cursor="hand2",
                      padx=10, pady=4, command=cmd, bd=0)
        b.bind("<Enter>", lambda _e: b.config(bg=SURFACE_HOVER) if str(b["state"]) == "normal" else None)
        b.bind("<Leave>", lambda _e: b.config(bg=BG3) if str(b["state"]) == "normal" else None)
        b.pack(side=side, padx=pad)
        return b
