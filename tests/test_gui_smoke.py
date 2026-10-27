"""
Chạy GUI thật (Tk mainloop) với server HTTP local: gửi request, Tests, lưu token,
che history, builder, Environment Manager, Import và Scenario.

Tự bỏ qua khi không có tkinter hoặc màn hình (trên Linux CI chạy bằng xvfb-run).
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    GUI_AVAILABLE = True
except Exception:   # không có tkinter / không có DISPLAY
    GUI_AVAILABLE = False

import store
from http_fixture import LocalApi


def _find(widget, widget_class: str):
    for child in widget.winfo_children():
        if child.winfo_class() == widget_class:
            return child
        found = _find(child, widget_class)
        if found is not None:
            return found
    return None


@unittest.skipUnless(GUI_AVAILABLE, "cần tkinter và màn hình (dùng xvfb-run trên Linux)")
class GuiSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name)
        # Không bao giờ đụng vào ~/.curl_runner thật của người chạy test.
        self.patches = [mock.patch.object(store, name, data / path.name) for name, path in (
            ("HIST_FILE", store.HIST_FILE), ("COLL_FILE", store.COLL_FILE), ("ENV_FILE", store.ENV_FILE),
            ("SCEN_FILE", store.SCEN_FILE), ("SETTINGS_FILE", store.SETTINGS_FILE),
        )] + [mock.patch.object(store, "DATA_DIR", data)]
        import app as app_module
        self.app_module = app_module
        self.patches += [mock.patch.object(app_module.messagebox, fn, lambda *a, **k: None)
                         for fn in ("showinfo", "showerror", "showwarning")]
        self.patches.append(mock.patch.object(app_module.messagebox, "askyesno", lambda *a, **k: True))
        for patch in self.patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def test_end_to_end(self) -> None:
        with LocalApi() as base:
            app = self.app_module.CurlRunnerApp()
            checks: list[tuple[str, bool, object]] = []
            crashed: list[BaseException] = []
            gen = self._script(app, base, checks)

            def advance(value):
                try:
                    cond = gen.send(value)
                except StopIteration:
                    app.after(10, app.quit)
                    return
                except BaseException as exc:   # noqa: BLE001 - surface in the test result
                    crashed.append(exc)
                    app.after(10, app.quit)
                    return
                poll(cond, time.time() + 20)

            def poll(cond, deadline):
                if cond():
                    app.after(1, advance, True)
                elif time.time() > deadline:
                    app.after(1, advance, False)
                else:
                    app.after(20, poll, cond, deadline)

            app.after(200, advance, None)
            app.mainloop()
            app.destroy()

        if crashed:
            raise crashed[0]
        failed = [f"{name}: {detail}" for name, ok, detail in checks if not ok]
        self.assertFalse(failed, "\n".join(failed))
        self.assertGreaterEqual(len(checks), 15)

    def _script(self, app, base: str, checks: list):
        def check(name: str, cond, detail: object = "") -> None:
            checks.append((name, bool(cond), detail))

        def set_text(widget, text: str) -> None:
            widget.delete("1.0", "end")
            widget.insert("1.0", text)

        def send(tab):
            before = tab.response
            app._send(tab)
            ok = yield (lambda: tab.response is not before and str(tab._send_btn["state"]) == "normal")
            return ok

        app.environments = {"QA": {"base": base}}
        app.active_env = "QA"
        app._refresh_env_selector()

        # Request + Tests + extractor lưu token vào environment
        tab = app.tabs[0]
        app._clear_ph(tab)
        set_text(tab._curl_tw, "curl -X POST {{base}}/login -d '{\"user\":\"dung\"}'")
        set_text(tab._tests_tw, "status == 200\njson $.data.token exists\ntoken = json:$.data.token")
        check("login request completes", (yield from send(tab)))
        check("tests pass", tab.test_ok is True, tab.test_results)
        check("token saved into environment", app.environments["QA"].get("token") == "tok-123", app.environments)
        check("Tests response tab shows ✓", "✓" in app.rtab_tests.cget("text"), app.rtab_tests.cget("text"))

        # Token dán thẳng → history lưu {{token}}
        app._new_tab(curl=f"curl {base}/me -H 'Authorization: Bearer tok-123'", tests="json $.user == dung")
        tab2 = app.tabs[-1]
        check("me request completes", (yield from send(tab2)))
        check("tests on tab 2 pass", tab2.test_ok is True, tab2.test_results)
        last = app.history[-1]["curl"] if app.history else ""
        check("history replaced token with {{token}}", "tok-123" not in last and "{{token}}" in last, last)

        # Test FAIL → panel chuyển sang tab Tests
        set_text(tab2._tests_tw, "status == 201")
        yield from send(tab2)
        check("failing test reported", tab2.test_ok is False and app.active_resp_tab == "tests",
              (tab2.test_ok, app.active_resp_tab))

        # Sửa trong builder vẫn giữ -u / -k
        app._new_tab(curl=f"curl -k -u admin:pw {base}/health")
        tab3 = app.tabs[-1]
        tab3._url_var.set(f"{base}/health?edited=1")
        parsed, curl = app._prepare_request_from_tab(tab3, {})
        check("builder keeps -u/-k", parsed["auth"] == ("admin", "pw") and parsed["verify_ssl"] is False, parsed)
        check("builder curl keeps -u/-k", "-u admin:pw" in curl and "-k" in curl, curl)

        # Response của tab khác không vẽ đè lên panel của tab đang xem
        app._switch_tab(0)
        app._send(tab3)
        yield (lambda: tab3.response is not None and str(tab3._send_btn["state"]) == "normal")
        check("background tab response not drawn", '"items"' not in app.body_tw.get("1.0", "end"))

        # Environment Manager che giá trị bí mật
        app._open_env_editor()
        yield (lambda: True)
        win = [w for w in app.winfo_children() if w.winfo_class() == "Toplevel"][-1]
        tree = _find(win, "Treeview")
        rows = {tree.item(i, "values")[0]: tree.item(i, "values") for i in tree.get_children()}
        check("secret value masked", rows["token"][1] == "••••••" and rows["token"][2] == "🔒 auto", rows)
        check("normal value visible", rows["base"][1] == base, rows)
        win.destroy()

        # Import Postman qua GUI
        collection = {"info": {"name": "Imported"}, "item": [
            {"name": "Health", "request": {"method": "GET", "url": "{{base}}/health"},
             "event": [{"listen": "test", "script": {"exec": ["pm.response.to.have.status(200);"]}}]}]}
        path = Path(self.tmp.name) / "collection.json"
        path.write_text(json.dumps(collection), encoding="utf-8")
        app._import_from_path(str(path))
        item = (app.collections.get("Imported") or [{}])[0]
        check("collection imported with tests", item.get("assertions") == "status == 200", item)
        app._open_coll_item_new_tab("Imported", item.get("id"))
        check("opening item loads its Tests", app._current_tests(app.tabs[-1]) == "status == 200")

        # Scenario: import tab đang mở (kèm Tests) rồi chạy
        from ui_scenario import ScenarioWindow
        window = ScenarioWindow(app)
        yield (lambda: True)
        window._import_open_tabs()
        steps = window._steps()
        check("scenario imported tabs with tests",
              any(s.get("assertions") == "status == 200" for s in steps), [s.get("assertions") for s in steps])
        window.stop_on_fail_var.set(False)
        window._run_scenario()
        check("scenario finished", (yield (lambda: not window.running)))
        check("scenario produced results", len(window.step_results) == len(steps),
              (len(window.step_results), len(steps)))
        window._on_close()


if __name__ == "__main__":
    unittest.main()
