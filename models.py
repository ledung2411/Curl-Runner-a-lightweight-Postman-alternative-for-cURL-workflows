# models.py — Data models
# type: ignore
import uuid


class RequestTab:
    """Lưu toàn bộ state của 1 tab request (curl, options, response...)."""
    _counter = 0

    def __init__(self, name: str | None = None, curl: str = "", pre_script: str = "", tests: str = ""):
        RequestTab._counter += 1
        self.id         = str(uuid.uuid4())[:8]
        self.name       = name or f"Tab {RequestTab._counter}"
        self.curl       = curl
        self.pre_script = pre_script
        self.tests      = tests      # assertion + extractor chạy sau khi có response
        self.builder_method = "GET"
        self.builder_url = ""
        self.builder_headers = ""
        self.builder_body = ""
        self.builder_dirty = False

        # Response state — được set sau khi gửi request
        self.response     = None   # requests.Response
        self.parsed: dict | None = None
        self.elapsed: float | None = None
        self.body_text    = ""
        self.detected_enc = ""
        self.pre_logs: list[str] = []
        self.ai_analysis  = ""
        self.test_results: list[str] = []
        self.test_ok: bool | None = None   # None = không có test

        # Widget references — được set bởi UI khi build tab content
        self._frame       = None   # tk.Frame
        self._curl_tw     = None   # tk.Text
        self._pre_tw      = None   # tk.Text
        self._tests_tw    = None   # tk.Text
        self._request_frame = None # tk.Frame
        self._method_var  = None   # tk.StringVar
        self._url_var     = None   # tk.StringVar
        self._headers_tree = None  # ttk.Treeview
        self._header_key_var = None # tk.StringVar
        self._header_value_var = None # tk.StringVar
        self._body_builder_tw = None # tk.Text
        self._send_btn    = None   # tk.Button
        self._status_lbl  = None   # tk.Label
        self._env_hint_lbl= None   # tk.Label
        self._nb          = None   # ttk.Notebook
        self._var_ssl     = None   # tk.BooleanVar
        self._var_redirect= None   # tk.BooleanVar
        self._var_decode  = None   # tk.BooleanVar
        self._timeout_var = None   # tk.StringVar
        self._repeat_var  = None   # tk.StringVar
        self._ph_active   = False  # placeholder active flag
        self._builder_dirty = False
        self._syncing_builder = False
        self._parse_after = None
        self._parsed_extras: dict = {}  # auth/-k/-m/form/binary body từ lần parse curl gần nhất
