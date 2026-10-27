# Curl Runner — Đánh giá, đề xuất cải tiến & lộ trình

Tài liệu này tổng hợp kết quả review toàn bộ mã nguồn (bản Python/Tkinter và bản WinUI/C#),
các lỗi đã được sửa, so sánh với Bruno/Postman, các vấn đề còn tồn tại và lộ trình đề xuất.

**Cập nhật:** đã hoàn thành giai đoạn 0 và 4 hạng mục ưu tiên của giai đoạn 2–3 (CLI cho CI, Tests cho từng request,
import Postman/Bruno/HAR, biến bí mật + che history) — xem mục 6. Bản WinUI chưa có các tính năng mới này.

---

## 1. Tổng quan hiện trạng

| Hạng mục | Hiện trạng |
|---|---|
| Ứng dụng | 2 bản song song: **Python/Tkinter** (`app.py` + `ui_*.py`, ~6.000 dòng) và **WinUI 3/C#** (`winui/`, .NET 10) |
| Dữ liệu | Cả 2 bản đọc/ghi chung `~/.curl_runner/*.json` (history, collections, environments, scenarios) |
| Lõi nghiệp vụ | `core.py` (parse curl, gửi request, decode, AI), `scenario_report.py`; C#: `Services/*` |
| Test | Trước review: 3 test Python (report) + 6 test C#. Không có CI |
| Điểm mạnh | Tính năng phong phú (multi-tab, builder, scenario song song, extract/assert, report JUnit, AI local/Ollama), có redact dữ liệu nhạy cảm trước khi gửi AI, giới hạn kích thước render response lớn |
| Điểm yếu chính | Parser curl tự viết thiếu nhiều trường hợp; `app.py` là "god class" 2.600 dòng; logic bị nhân đôi (parser trong Compare, rule engine Python vs C#); lưu file không an toàn khi lỗi; ít test |

---

## 2. Các lỗi đã sửa (review lần 1)

Mỗi lỗi dưới đây đều có unit test; 18/21 test mới **thất bại trên code cũ** và **qua trên code mới**.

### 2.1 Parser curl (`core.py`)

| # | Lỗi | Ảnh hưởng | Cách sửa |
|---|---|---|---|
| 1 | Giá trị của option không được hỗ trợ bị hiểu nhầm thành URL (`curl -o out.txt https://...` → URL = `out.txt`) | Gửi request sai URL | Danh sách option có giá trị của curl; bỏ qua cả option lẫn giá trị |
| 2 | Không hiểu option dính/gộp: `-XPOST`, `-H'A: b'`, `-sSL`, `-d@file` | Parse sai method/header/body | Tách short option giống curl |
| 3 | `curl https://x -X` (thiếu giá trị) → `IndexError` khó hiểu | Crash/thông báo khó hiểu | `ValueError` rõ ràng "Option -X thiếu giá trị" |
| 4 | Nhiều `-d` → chỉ giữ cái cuối | Mất dữ liệu form | Nối bằng `&` như curl |
| 5 | `-F name=value` gửi field thường như **file upload**; `-F file=@path` gửi chuỗi `@path` thay vì nội dung file | Server nhận sai multipart | Field thường gửi không filename; `@file` upload thật, hỗ trợ `;type=`/`;filename=`; `<file` |
| 6 | `-u user` (không có `:`) tạo tuple 1 phần tử → `requests` lỗi | Crash khi gửi | Mật khẩu rỗng như curl |
| 7 | Chrome "Copy as cURL (bash)" dùng `$'...'` → parse sai body | Không chạy được curl copy từ DevTools | Tokenizer shell riêng hỗ trợ ANSI-C quoting |
| 8 | Chrome "Copy as cURL (cmd)" dùng `^"...^"` | Không parse được trên Windows | Bỏ escape `^` khi phát hiện định dạng cmd |
| 9 | Bên trong `"..."`, `shlex` xử lý `\$` khác bash | Body sai ký tự `$` | Áp dụng đúng quy tắc POSIX/bash |
| 10 | Header trùng tên khác hoa/thường bị gửi cả hai | Server nhận header mâu thuẫn | Header sau ghi đè header trước (không phân biệt hoa/thường) |
| 11 | Thiếu `-G`, `-I`, `--json`, `--data-urlencode`, `-b`, `-e`, `curl.exe` | Không dùng được các lệnh curl phổ biến | Bổ sung |
| 12 | `-d @file` mở file không đóng | Rò rỉ file handle | `with open(...)`, lỗi đọc file báo rõ ràng |

### 2.2 Gửi request & dữ liệu

| # | Lỗi | Cách sửa |
|---|---|---|
| 13 | Body JSON bị `json.loads` rồi serialize lại → đổi byte gửi đi (`1.50` → `1.5`, khoảng trắng, tiếng Việt thành `\uXXXX`) | Gửi đúng từng byte UTF-8 người dùng nhập |
| 14 | `beautify_curl_body` sinh lệnh curl **hỏng** khi JSON có dấu `'` (dùng `\'` trong single quote — bash không hiểu) | Quote lại đúng chuẩn shell (`'\''`, escape `"`/`$`/`` ` `` trong double quote) |
| 15 | `store.save` ghi đè trực tiếp: crash giữa chừng → hỏng file; file JSON hỏng → `load` trả rỗng → lần save sau **xoá sạch dữ liệu cũ** | Ghi file tạm + `os.replace` (nguyên tử); file hỏng được đổi tên thành `*.corrupt-<thời gian>.bak` |
| 16 | `environments.json` = `{}` → crash khi mở app | Luôn có environment `Default` |
| 17 | Import thiếu `requests` → tự chạy `pip install` ngầm khi import | Báo lỗi rõ ràng, không tự cài |

### 2.3 Giao diện (`app.py`, `ui_scenario.py`, `ui_converter.py`)

| # | Lỗi | Cách sửa |
|---|---|---|
| 18 | Pre-request script bắt đầu bằng comment (ví dụ nút **📋 Ví dụ**) **không bao giờ chạy** vì check `startswith("#")` | Chỉ bỏ qua khi toàn bộ script là comment/dòng trống |
| 19 | `-k` và `--max-time` trong curl bị checkbox *Verify SSL* / ô *Timeout* ghi đè | Flag trong curl được ưu tiên |
| 20 | Sửa trong Request builder làm **mất** `-u`, `-k`, `-m`, form `-F` và body nhị phân (gửi chuỗi `[binary body: N bytes]`) | Builder giữ lại các thông tin này; sinh lại curl có `-u`/`-k`/`--max-time`/`-F` |
| 21 | Gửi request ở tab A rồi chuyển sang tab B → response của A hiện ở panel của B; đóng tab khi đang gửi → lỗi Tcl | Chỉ vẽ panel cho tab đang chọn, kiểm tra tab còn tồn tại |
| 22 | Environment Manager: đổi environment trong combobox làm mất chỉnh sửa chưa lưu; thêm/xoá environment áp dụng ngay cả khi không bấm Lưu | Chỉnh sửa trên bản nháp, chỉ áp dụng khi "Lưu & Đóng" |
| 23 | Scenario: worker thread đọc `tk.BooleanVar` (không thread-safe); đóng cửa sổ khi đang chạy → exception | Đọc giá trị ở main thread; dừng run và bỏ qua callback khi cửa sổ đã đóng |
| 24 | Converter "JSON string → Text" biến tiếng Việt thành mojibake (`tiáº¿ng`) | `encode("latin-1", "backslashreplace")` trước `unicode_escape` |
| 25 | Pre-script gán `env['port'] = 8080` → `apply_env` lỗi `TypeError` | Ép giá trị env về `str` |

### 2.4 WinUI / C# (⚠️ chưa biên dịch được trong môi trường review — cần chạy `dotnet test` trên Windows)

| # | Lỗi | Cách sửa |
|---|---|---|
| 26 | Tokenizer bỏ mất `\` trong `"..."` → `-d "{\"a\":\"x\ny\"}"` thành `xny` | Quy tắc escape giống bash |
| 27 | Giá trị option không hỗ trợ bị hiểu thành URL; không hiểu `-XPOST`, `-sSL` | Tách short option + danh sách option có giá trị |
| 28 | `-X GET -d ...` bị đổi thành POST; nhiều `-d` chỉ giữ cái cuối | Method mặc định tính sau khi parse; nối `&` |
| 29 | Thiếu `-u`, `-A`, `-b`, `-e`, `-I`, `--json`, `--data-urlencode`, `--oauth2-bearer` | Bổ sung (`-u` → header `Authorization: Basic`) |
| 30 | `Content-Type` không chuẩn (vd. có `;` cuối) làm `MediaTypeHeaderValue.Parse` ném lỗi | Gửi header không validate |
| 31 | File JSON hỏng → load rỗng → save đè mất dữ liệu (dùng chung với bản Python!) | Sao lưu `*.corrupt-*.bak` trước |

### 2.5 Vệ sinh repo
- Gỡ `build/` và `dist/CurlRunner.exe` (~38 MB) khỏi git — vốn đã có trong `.gitignore`. Build lại bằng `build_exe.bat`; nên phát hành `.exe` qua **GitHub Releases**.
- Thêm CI `.github/workflows/python-tests.yml` chạy unit test trên Python 3.11 và 3.13.

---

## 3. Vấn đề còn tồn tại (chưa sửa) — xếp theo ưu tiên

### 🔴 Cao
1. ~~**Lộ bí mật trong history**~~ ✅ Đã xử lý ở bản Python (mục 6.4). Bản WinUI vẫn lưu curl nguyên văn.
2. **Pre-request script không có sandbox** (Python `exec` toàn quyền). Đã ghi cảnh báo trong tài liệu.
   → Đề xuất: khi import collection/scenario từ ngoài, hiển thị script và yêu cầu xác nhận trước khi chạy lần đầu.
3. **Không huỷ được request đang chạy**: Repeat tối đa 1.000 lần, timeout dài → chỉ có thể đợi.
   → Thêm nút *Cancel* (dùng `threading.Event` giữa các lần lặp; WinUI đã có `CancellationToken`).
4. **Kiểm tra Ollama chạy đồng bộ trên UI thread** (`_analyze_response` → `get_ollama_status`, timeout 2,5 s) làm đơ giao diện.

### 🟠 Trung bình
5. **`app.py` 2.600 dòng, một class**: khó test, khó sửa. UI, state, I/O trộn lẫn.
6. **Logic bị nhân đôi**: parser curl thứ 2 trong `ui_compare._normalize_curl` (vẫn dùng `shlex`, không có các sửa ở trên); rule engine scenario viết 2 lần (Python + C#) dễ lệch hành vi.
   (Trong bản Python, GUI và CLI đã dùng chung `scenario_engine.py`.)
7. **Parity Python ↔ C#** chưa đủ: WinUI chưa hỗ trợ multipart `-F`, `-d @file`, `$'...'`; pre-request script WinUI chỉ hỗ trợ tập con cú pháp.
8. **File dữ liệu không có `schema_version`**: 2 app đọc chung, một bên đổi format là bên kia hỏng.
9. **`-d` không có Content-Type**: curl thật tự gửi `application/x-www-form-urlencoded`, app không gửi → khác hành vi curl.
10. **Scenario**: chưa có pre-request script/option SSL theo step, chưa có retry; JSONPath đã thêm `[-1]` và `['key']` nhưng chưa có filter.
11. **Type checking gần như tắt** (`pyrightconfig.json` tắt ~20 rule, `# type: ignore` đầu file).

### 🟡 Thấp
12. Header có ký tự ngoài latin-1 (tiếng Việt) bị `http.client` từ chối — nên báo lỗi thân thiện.
13. ~~Report CSV có thể bị "CSV injection"~~ ✅ Đã xử lý.
14. Cửa sổ Scenario/Compare/Converter không áp dụng cài đặt font đã lưu.
15. Treeview của Tk có thể trả giá trị số dạng `int` (mất số 0 đầu: `007` → `7`) — nên dùng `tree.set()` hoặc lưu dữ liệu song song ngoài widget.

---

## 4. Đề xuất cải tiến

### 4.1 Kiến trúc
- Tách `app.py` thành: `controllers/request_controller.py` (gửi request, repeat, history), `views/` (widget), `state.py` (RequestTab thuần dữ liệu, không giữ widget).
- Một module parser duy nhất (`core.parse_curl` + `core.shell_split`) dùng cho Request, Compare, Scenario, Report.
- Đưa phần không phụ thuộc UI (parser, executor, rule engine, report) thành package `curlrunner_core` → tái sử dụng cho **CLI**.
- Bộ **golden test** dùng chung: file `tests/fixtures/curl_cases.json` (input curl → kết quả mong đợi) chạy ở cả Python và C# để đảm bảo 2 bản parse giống nhau.

### 4.2 Bảo mật & dữ liệu
- Biến môi trường loại *secret* (ẩn trên UI, lưu qua Windows Credential Manager / `keyring`).
- Redact history; tuỳ chọn tắt history.
- `schema_version` + migration cho file JSON; backup tự động trước khi migrate.

### 4.3 Trải nghiệm người dùng
- Nút Cancel, thanh tiến độ cho Repeat; thống kê Repeat: min / avg / p95 / tỉ lệ lỗi.
- Timing chi tiết (DNS, connect, TLS, TTFB) — WinUI có thể dùng `SocketsHttpHandler` + `DiagnosticListener`.
- Cookie jar theo environment; cấu hình proxy / client certificate.
- Phím tắt: `Ctrl+Enter` gửi request, `Ctrl+S` lưu vào collection, `Ctrl+T` tab mới.

### 4.4 Tính năng "kiểu Postman"
- Import: Postman Collection v2.1, HAR (từ DevTools), OpenAPI 3.
- Export code: Python `requests`, JS `fetch`, C# `HttpClient`, PowerShell.
- **CLI headless** cho CI: `python -m curlrunner run scenarios.json --env QA --report junit.xml` (đã có sẵn exporter JUnit).
- Scenario: data-driven (chạy theo từng dòng CSV), retry/backoff theo step, JSONPath đầy đủ (vd. `jsonpath-ng`).

---

## 5. Lộ trình đề xuất

| Giai đoạn | Thời gian (ước tính) | Mục tiêu | Hạng mục chính | Tiêu chí hoàn thành |
|---|---|---|---|---|
| **0. Ổn định** ✅ | Đã xong | Không mất dữ liệu, parse đúng curl phổ biến | Mục 2: parser, store nguyên tử, sửa lỗi UI, 21 test mới, CI | CI xanh; `dotnet test` xanh trên Windows |
| **1. Nền móng** | 2–3 tuần | Dễ bảo trì, đảm bảo parity | Tách `app.py`; Compare dùng parser chung; golden test Python + C#; `schema_version`; bật dần pyright `standard`; CI chạy thêm `dotnet test` trên `windows-latest` | `app.py` < 800 dòng; golden test chạy ở 2 nền tảng |
| **2. An toàn & UX** | 2–3 tuần | Không lộ bí mật, không đơ UI | ✅ Secret vars + redact history; ✅ CSV-injection; ⬜ Cancel request; ⬜ Ollama check bất đồng bộ; ⬜ xác nhận script khi import; ⬜ thông báo lỗi header ngoài latin-1 | Không còn token plain text trong `history.json` mặc định |
| **3. Năng suất** | 3–4 tuần | Thay thế được Postman cho luồng cURL | ✅ Import Postman/Bruno/HAR; ⬜ OpenAPI; ⬜ export code; ✅ CLI headless + JUnit + data-driven; ✅ Tests cho từng request; ⬜ thống kê Repeat; ⬜ timing chi tiết | Chạy được scenario trong GitHub Actions bằng CLI |
| **4. Hợp nhất & phát hành** | Liên tục | Một sản phẩm, phát hành chuyên nghiệp | Chọn WinUI là UI chính trên Windows, Python core cho CLI/đa nền tảng; GitHub Releases tự động (exe/zip đã ký); auto-update; tài liệu song ngữ | Release có changelog, artifact ký số, cài đặt 1 click |

### Thứ tự ưu tiên tiếp theo
1. Chạy `dotnet test winui/CurlRunner.WinUI.sln` trên Windows để xác nhận phần sửa C#; thêm job `windows-latest` vào CI.
2. Nút **Cancel** request + kiểm tra Ollama bất đồng bộ (mục 3.3, 3.4).
3. Cho `ui_compare.py` dùng `core.shell_split`/`parse_curl` (xoá parser trùng).
4. Đưa 4 tính năng mới sang WinUI (hoặc quyết định WinUI chỉ là UI, gọi lõi Python/CLI).
5. Sinh code mẫu (Python/JS/C#) và import OpenAPI — 2 khoảng trống còn lại so với Bruno/Postman.

---

## 6. Đã làm sau review (bản Python)

| # | Hạng mục | Nội dung | Test |
|---|---|---|---|
| 6.1 | **CLI cho CI** (`cli.py`) | `run` scenario/collection/Postman/Bruno; exit code 0/1/2; report JUnit/HTML/CSV/JSON; data-driven `--data` CSV/JSON; biến `--var`, `CURLRUNNER_VAR_*`, environment của app hoặc Postman; `request`, `import`, `list` | `tests/test_cli.py` |
| 6.2 | **Engine dùng chung** (`scenario_engine.py`) | Extract/assert + runner tách khỏi Tk; thêm `time < N`, `header X exists`, `[-1]`, `['key']`, biến `{{...}}` trong rule | `tests/test_scenario_engine.py` |
| 6.3 | **Tests cho từng request** | Tab ✅ Tests, kết quả ở tab Tests của response, lưu giá trị vào environment, lưu cùng collection, dùng cho CLI và Scenario | kiểm thử logic với tkinter giả lập |
| 6.4 | **Biến bí mật** (`redaction.py`) | Nhận diện theo tên + đánh dấu thủ công; che trong history (`{{biến}}` / `[REDACTED]`), Info, AI; Environment Manager hiện `••••••`; che lại history cũ | `tests/test_redaction.py` |
| 6.5 | **Import** (`importers.py`) | Postman v2.x + environment, Bruno, HAR; dịch test phổ biến; ghi chú phần không chuyển được | `tests/test_importers.py` (có chạy end-to-end) |

---

## 7. So sánh với Bruno / Postman (sau khi làm mục 6)

| Tiêu chí | Curl Runner | Bruno | Postman |
|---|---|---|---|
| Curl là định dạng gốc (dán – chạy – lưu – mở lại vẫn là curl) | ✅ | ⚠️ chuyển sang `.bru` | ⚠️ chuyển sang request Postman |
| So sánh nhiều request/response (diff theo key) | ✅ | ❌ | ❌ |
| AI phân tích response chạy local, miễn phí | ✅ Ollama | ❌ | ⚠️ Postbot (cloud) |
| Scenario: group tuần tự, step trong group song song | ✅ | ⚠️ tuần tự | ✅ (runner + load test) |
| Assertion không cần code | ✅ Scenario + từng request | ✅ | ⚠️ JS |
| Chạy trên CI, JUnit, data-driven | ✅ `cli.py` | ✅ `bru run` | ✅ Newman / Postman CLI |
| Import collection từ công cụ khác | ✅ Postman, Bruno, HAR | ✅ Postman, Insomnia, OpenAPI | ✅ nhiều định dạng |
| Biến bí mật | ⚠️ che hiển thị/history, file vẫn lưu văn bản | ✅ | ✅ Vault |
| Không cần tài khoản, offline | ✅ | ✅ | ⚠️ |
| Giao thức ngoài HTTP (GraphQL UI, gRPC, WebSocket) | ❌ (GraphQL gửi dạng JSON) | ✅ | ✅ |
| Auth helper (OAuth2, AWS SigV4, Digest) | ❌ | ✅ | ✅ |
| Script JS trước/sau request | ⚠️ Python trước request | ✅ | ✅ |
| Folder, biến cấp collection | ❌ (folder import thành tiền tố tên) | ✅ | ✅ |
| Sinh code mẫu, OpenAPI import | ❌ | ✅ | ✅ |
| Làm việc nhóm | ❌ file JSON | ✅ git | ✅ cloud |
| Đa nền tảng | ⚠️ Python chạy được, WinUI chỉ Windows | ✅ | ✅ |

Bảng dựa trên hiểu biết về Bruno/Postman tại thời điểm viết; hai công cụ này cập nhật nhanh.

**Định vị đề xuất:** công cụ debug *curl-first* — dán từ DevTools/log, chạy, so sánh, phân tích bằng AI local,
rồi đưa thẳng lên CI bằng `cli.py`. Không cạnh tranh trực diện về nền tảng làm việc nhóm hay mock/monitor.
