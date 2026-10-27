# Curl Runner User Manual

Tài liệu này hướng dẫn chi tiết cách dùng Curl Runner cho developer và tester: chạy curl, quản lý environment, đọc response, dùng AI phân tích lỗi, chạy repeat request và tạo API Scenario nhiều bước.

---

## 1. Tổng quan

Curl Runner là desktop API client nhẹ, tập trung vào workflow thường gặp khi debug API:

- Paste curl từ browser/devtools và chạy trực tiếp
- Quản lý nhiều tab request
- Lưu history và collections
- Dùng environment variable như `{{base_url}}`, `{{token}}`
- Chạy pre-request script bằng Python
- Tìm kiếm trong response
- Tự gọi API nhiều lần bằng Repeat
- Chạy API Scenario theo sequential/parallel groups
- Extract biến từ response và assertion kết quả (cho Scenario và cho từng request)
- Dùng AI để phân tích lỗi response bằng Ollama local hoặc OpenAI Billing API
- Import Postman / Bruno / HAR
- Chạy scenario/collection trên CI bằng `cli.py`
- Che token/mật khẩu trong history, AI và màn hình

---

## 2. Cài đặt

### 2.1 Yêu cầu

- Windows
- Python 3.10+
- pip
- `requests`
- `charset-normalizer`
- `ttkbootstrap` cho giao diện hiện đại
- Ollama nếu muốn dùng AI Analysis miễn phí local
- PyInstaller nếu muốn build `.exe`

### 2.2 Chạy từ source

```powershell
git clone https://github.com/ledung2411/Curl-runner.git
cd Curl-runner
pip install -r requirements.txt
python main.py
```

### 2.3 Build file exe

```powershell
pip install -r requirements.txt
python -m PyInstaller CurlRunner.spec
```

Hoặc chạy:

```bat
build_exe.bat
```

File build nằm tại:

```text
dist\CurlRunner.exe
```

---

## 3. Cấu trúc giao diện

Ứng dụng có 3 vùng chính:

| Vùng | Mục đích |
|---|---|
| Sidebar trái | History và Collections |
| Center | Request builder, curl input, options, pre-request script |
| Right panel | Response body, headers, request info, log, AI analysis |

Topbar có các chức năng:

| Nút | Mục đích |
|---|---|
| Manage | Quản lý environments |
| Scenario | Mở API Scenario runner |
| Compare | So sánh nhiều curl |
| Convert | Convert String / JSON |
| Font | Chỉnh font UI và monospace |

Theme UI dùng `ttkbootstrap` để làm các widget như Combobox, Notebook và bảng Treeview sạch hơn. Nếu thư viện chưa được cài, app vẫn tự fallback về theme Tkinter mặc định để không chặn việc chạy request.

---

## 4. Chạy request cơ bản

### 4.1 Paste curl

Paste curl vào tab **curl**:

```bash
curl https://httpbin.org/get
```

Hoặc curl có method/header/body:

```bash
curl -X POST https://api.example.com/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"secret"}'
```

Nhấn **SEND REQUEST** để chạy.

Khi paste curl, app tự tách dữ liệu sang tab **Request**:

| Field | Nguồn từ curl |
|---|---|
| Method | `-X`, hoặc tự suy ra `GET` / `POST` |
| URL | URL trong curl hoặc `--url` |
| Headers | Các flag `-H` / `--header` |
| Body | Các flag `-d`, `--data`, `--data-raw`, `--data-binary` |

Nếu paste xong mà muốn parse lại thủ công, bấm **↘ Parse**.

### 4.2 Request Builder

Tab **Request** hoạt động giống Postman ở mức cơ bản:

- Chọn Method
- Nhập/sửa URL
- Sửa Headers trong bảng 2 cột **Header** và **Value**
- Sửa Body raw text hoặc JSON

Khi bạn chỉnh tab **Request**, app sẽ gửi request theo dữ liệu builder. Nếu bạn chỉ paste curl và không chỉnh builder, app vẫn gửi raw curl gốc để giữ các option curl đặc biệt.

### 4.3 Options của request

| Option | Ý nghĩa |
|---|---|
| Verify SSL | Bật/tắt verify SSL certificate |
| Follow Redirect | Cho phép follow redirect |
| Auto Decode | Tự detect encoding của response |
| Timeout | Timeout mỗi request, tính bằng giây |
| Repeat | Số lần gọi cùng request liên tiếp |

### 4.4 Repeat request

Ô **Repeat** dùng để auto call API nhiều lần.

Ví dụ:

- `Repeat = 1`: gọi 1 lần
- `Repeat = 5`: gọi 5 lần liên tiếp
- `Repeat = 100`: gọi 100 lần liên tiếp

Khi Repeat lớn hơn 1:

- App chạy tuần tự trong background
- Response panel hiển thị response của lần cuối
- Tab Log hiển thị từng attempt, status code và thời gian
- Nếu một lần gọi lỗi exception, repeat dừng và hiển thị lỗi

Giới hạn hiện tại: `1000` lần.

---

## 5. Environments

Environment giúp bạn dùng biến trong curl:

```bash
curl {{base_url}}/api/users \
  -H 'Authorization: Bearer {{token}}'
```

### 5.1 Tạo environment

1. Nhấn **Manage**
2. Tạo environment mới hoặc chọn environment hiện có
3. Thêm biến:

| Variable | Value |
|---|---|
| `base_url` | `https://api.example.com` |
| `token` | `eyJhbGciOi...` |

### 5.2 Dùng biến trong curl

Cú pháp:

```text
{{variable_name}}
```

Ví dụ:

```bash
curl {{base_url}}/orders/{{order_id}}
```

### 5.3 Hint biến

Khi bạn nhập curl, app hiển thị hint:

- `✓ token`: biến đã tồn tại trong environment
- `✗ token`: biến chưa tồn tại

---

## 6. Pre-request Script

Mỗi request tab có tab **Pre-request Script**.

Script chạy trước khi gửi request, dùng cho:

- Set token động
- Tạo timestamp
- Gọi API login phụ
- Chuẩn bị biến environment runtime

> ⚠️ Script là Python thật, chạy với toàn quyền của app (không phải sandbox):
> có thể đọc/ghi file, gọi lệnh hệ thống... Chỉ chạy script do bạn viết hoặc đã đọc kỹ,
> nhất là khi nhận collection/scenario từ người khác.
>
> Script có thể bắt đầu bằng comment; chỉ khi **toàn bộ** script là comment/dòng trống thì mới được bỏ qua.

### 6.1 API có sẵn trong script

| API | Mục đích |
|---|---|
| `set_env(key, value)` | Set biến environment runtime |
| `env` | Dict environment hiện tại |
| `log(message)` | Ghi vào Script Log |
| `requests` | Gọi HTTP request khác |
| `json`, `re` | Module Python thông dụng |

### 6.2 Ví dụ set timestamp

```python
import time
set_env('timestamp', str(int(time.time())))
log('timestamp ready')
```

### 6.3 Ví dụ login lấy token

```python
resp = requests.post(
    env.get('base_url', '') + '/auth/login',
    json={'username': 'admin', 'password': 'secret'},
    timeout=10
)

if resp.ok:
    token = resp.json()['data']['token']
    set_env('token', token)
    log(f'Token: {token[:20]}...')
else:
    log(f'Login failed: {resp.status_code}')
```

---

## 7. Response panel

Sau khi gửi request, response panel có các tab:

| Tab | Nội dung |
|---|---|
| Body | Response body, JSON được format/highlight nếu phù hợp |
| Headers | Response headers |
| Info | Request/response metadata |
| Log | Pre-request script log, Repeat log |
| AI | Kết quả AI Analysis |

### 7.1 Status, time, size

Header của response panel hiển thị:

- HTTP status
- response time
- response size

### 7.2 Copy response

Nhấn **Copy** để copy response body đang hiển thị.

### 7.3 Save response

Nhấn **Save** để lưu raw response content ra file `.json`, `.txt` hoặc định dạng khác.

### 7.4 Large response behavior

Để UI không bị lag:

- Response quá lớn sẽ bị giới hạn preview trong UI
- File save vẫn lưu raw response đầy đủ
- JSON lớn có thể không highlight chi tiết để tăng tốc
- Search giới hạn số vùng highlight

---

## 8. Search trong response

Thanh **Search** nằm trong response panel.

### 8.1 Phím tắt

| Phím | Hành động |
|---|---|
| `Ctrl+F` | Focus vào ô search |
| `Enter` | Tới kết quả tiếp theo |
| `Shift+Enter` | Về kết quả trước |
| `Escape` | Xoá search |

### 8.2 Tùy chọn

| Option | Ý nghĩa |
|---|---|
| Aa | Bật/tắt phân biệt hoa thường |
| Prev | Kết quả trước |
| Next | Kết quả sau |

Search hoạt động theo tab response hiện tại: Body, Headers, Info, Log hoặc AI.

---

## 9. History

History tự lưu request đã gửi.

### 9.1 Tìm history

Nhập keyword vào ô search trong sidebar.

Có thể tìm theo:

- method
- URL
- status code

### 9.2 Dùng lại request

- Double-click item trong history để load vào tab hiện tại
- Right-click để mở trong tab mới
- Right-click để lưu vào collection
- Xoá từng item hoặc xoá hết history

---

## 10. Collections

Collections dùng để lưu request thường dùng.

### 10.1 Lưu request vào collection

1. Nhập curl ở tab hiện tại
2. Nhấn **Collection**
3. Chọn collection và nhập tên request

### 10.2 Dùng request từ collection

- Double-click request để load vào tab hiện tại
- Right-click để mở trong tab mới
- Rename hoặc delete item

---

## 11. Compare và Convert

Nhấn **Compare** trên topbar để mở cửa sổ so sánh Curl, JSON, text hoặc string.

### 11.1 Mục đích

Compare giúp thấy khác biệt giữa nhiều nội dung:

- Curl: method, URL, headers, body, options
- JSON: path/key/value trong object hoặc array
- Text: từng dòng
- String: token hoặc từng ký tự

### 11.2 Cách dùng

- Chọn mode: `auto`, `curl`, `json`, `text`, hoặc `string`
- Paste nội dung vào từng panel
- Nhấn **So sánh**
- Dòng khác biệt được highlight
- Có thể thêm/xoá panel
- Có thể load curl từ các tab đang mở

Thanh **Search** trong Compare tìm trên phần **DIFF VIEW**:

- Nhập nhiều giá trị bằng dấu `|`, ví dụ `error|timeout|token`
- Scope `All panels`: tìm trong toàn bộ panel
- Scope `#1`, `#2`...: chỉ tìm trong panel được chọn
- **Prev / Next**: nhảy giữa các kết quả
- **Aa**: bật/tắt phân biệt hoa thường
- **Only results**: chỉ hiển thị các dòng match trong DIFF VIEW
- **Clear**: xoá từ khóa và highlight

Phần **DIFF VIEW** là read-only nhưng vẫn cho bôi đen copy text. Có thể dùng `Ctrl+C`, `Ctrl+A`, hoặc chuột phải để chọn **Copy**, **Select all**, **Copy all**.

Mode `auto` tự nhận dạng nội dung. Với `curl` và `json`, Compare align theo key/path nên khi một bên có thêm field mới, các field còn lại vẫn dễ đọc và không bị lệch dòng.

Với nội dung rất dài, Compare không giới hạn ký tự. App xử lý trong background và render kết quả theo từng batch để UI không bị đơ.

### 11.3 Convert String / JSON

Nhấn **Convert** trên topbar để mở công cụ chuyển đổi String / JSON.

Các mode hỗ trợ:

| Mode | Ý nghĩa |
|---|---|
| JSON Pretty | Format JSON dễ đọc |
| JSON Minify | Nén JSON thành một dòng |
| Input -> JSON string | Escape input thành JSON string literal |
| JSON string -> Text/JSON | Unescape JSON string; nếu text bên trong là JSON thì format đẹp |
| Lines -> JSON array | Mỗi dòng thành một phần tử trong JSON array |

Nút **Beautify** tự format JSON thường hoặc JSON string đã escape. Textbox tự xuống dòng theo chiều rộng ô khi nội dung dài. Nút **Load Response** lấy response body của tab hiện tại vào input. Nút **Copy Output** copy kết quả ra clipboard.

---

## 12. AI Analysis

AI Analysis đọc request/response đã redact và gợi ý:

- Tóm tắt lỗi
- Bằng chứng từ status/header/body
- Nguyên nhân có khả năng cao
- Cách sửa
- Bước kiểm tra tiếp theo

Kết quả được yêu cầu trả lời bằng tiếng Việt.

### 12.1 Free Local

Option **Free Local** dùng Ollama local.

Ưu điểm:

- Miễn phí
- Không cần OpenAI key
- Dữ liệu chạy local trên máy

Cài Ollama:

Khi bấm **AI Analyze**, app kiểm tra Ollama trước khi phân tích. Nếu chưa ready, app mở popup **Setup Ollama Local AI**.

Popup này hiển thị:

- Ollama CLI đã cài hay chưa
- Ollama server có đang chạy không
- Model local đã có hay chưa
- Log tiến độ khi cài đặt hoặc pull model

Các nút chính:

| Nút | Ý nghĩa |
|---|---|
| Install Ollama | Cài Ollama bằng script/installer chính thức |
| Start Ollama | Start server local |
| Pull llama3.2 | Tải model mặc định |
| Re-check | Kiểm tra lại trạng thái |
| Analyze now | Chạy phân tích sau khi ready |
| Open Download Page | Mở trang download để cài thủ công |

Nếu muốn cài bằng terminal:

```powershell
irm https://ollama.com/install.ps1 | iex
ollama pull llama3.2
```

Kiểm tra:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

### 12.2 Billing API

Option **Billing API** dùng OpenAI API.

Khi chọn option này:

- Nếu có `OPENAI_API_KEY`, app dùng key đó
- Nếu chưa có key, app bật popup nhập API key
- Nếu bấm Cancel, app quay lại Free Local

Có thể set trước:

```powershell
setx OPENAI_API_KEY "sk-..."
setx OPENAI_MODEL "gpt-5.4-mini"
```

### 12.3 AI provider options

| Option | Provider | Cần billing |
|---|---|---|
| Free Local | Ollama | Không |
| Billing API | OpenAI API | Có |

### 12.4 Redaction

Trước khi gửi context cho AI, app cố gắng redact:

- Authorization
- Cookie / Set-Cookie
- token
- api key
- password
- secret

Lưu ý: redaction là best-effort. Với production data hoặc dữ liệu khách hàng, nên dùng Free Local.

### 12.5 Lỗi thường gặp

| Lỗi | Cách xử lý |
|---|---|
| Cannot connect to Ollama | Cài/mở Ollama, pull model |
| No Ollama models installed | Chạy `ollama pull llama3.2` |
| Setup Ollama install failed | Dùng **Open Download Page** trong popup và cài thủ công |
| OpenAI 401 | Kiểm tra API key |
| OpenAI billing/quota | Thêm billing hoặc dùng Free Local |

---

## 13. API Scenario

API Scenario dùng để chạy workflow nhiều API.

Một scenario gồm nhiều step. Mỗi step có:

- Name
- Group
- Enabled
- curl
- Extractors
- Assertions

### 13.1 Sequential và parallel

Rule chạy:

- App chạy Group thấp trước Group cao
- Step cùng Group chạy parallel
- Group sau chỉ bắt đầu khi Group trước hoàn tất

Ví dụ:

| Step | Group | Ý nghĩa |
|---|---:|---|
| Login | 1 | Chạy trước |
| Get Profile | 2 | Chạy parallel |
| Get Orders | 2 | Chạy parallel |
| Get Notifications | 2 | Chạy parallel |
| Logout | 3 | Chạy cuối |

### 13.2 Tạo scenario mới

1. Nhấn **Scenario**
2. Nhấn **New**
3. Nhập tên scenario
4. Nhấn **Add Step**
5. Nhập Name, Group, curl
6. Nhấn **Update Step** hoặc **Save**

### 13.3 Import từ tab đang mở

Nếu bạn đã có nhiều curl ở các tab:

1. Mở **Scenario**
2. Nhấn **Import Open Tabs**
3. App tạo step từ từng tab có curl

### 13.4 Run scenario

Nhấn **Run Scenario**.

Kết quả hiển thị:

- Status từng step
- Time từng step
- Log group/step
- Summary pass/fail

### 13.5 Stop on fail

Nếu bật **Stop on fail**:

- App vẫn chờ group hiện tại chạy xong
- Nếu có step fail, app không chạy group tiếp theo

Nếu tắt:

- App tiếp tục chạy group sau dù có step fail

### 13.6 Stop

Nút **Stop** yêu cầu dừng scenario.

Lưu ý: request đang chạy sẽ hoàn tất, app sẽ skip group tiếp theo.

### 13.7 Export report

Sau khi scenario chạy xong, nhấn **Export Report** và chọn định dạng:

| Định dạng | Mục đích |
|---|---|
| HTML Report | Báo cáo trực quan để mở bằng browser hoặc gửi cho team |
| CSV Results | Phân tích kết quả bằng Excel hoặc Google Sheets |
| JUnit XML | Đưa kết quả vào CI và test report viewer |

Report gồm tên scenario, environment, tổng số pass/fail/skip, method, URL, status, thời gian và assertion của từng step.

Để tránh lộ credential, report không lưu full curl/header hoặc giá trị biến extract. Các query parameter có tên như `token`, `key`, `secret`, `password`, `auth`, `signature` được thay bằng `[REDACTED]`.

---

## 14. API Scenario Extractors

Extractors lấy dữ liệu từ response và lưu vào runtime env.

### 14.1 Cú pháp

```text
variable_name = json:$.path.to.value
variable_name = header:Header-Name
variable_name = regex:pattern
```

### 14.2 Extract từ JSON

Response:

```json
{
  "data": {
    "token": "abc123",
    "user": {
      "id": 10
    }
  }
}
```

Extractor:

```text
token = json:$.data.token
user_id = json:$.data.user.id
```

### 14.3 Extract từ header

```text
request_id = header:X-Request-Id
content_type = header:Content-Type
```

### 14.4 Extract bằng regex

Regex lấy group 1 nếu có capture group:

```text
order_id = regex:"orderId"\s*:\s*"([^"]+)"
```

Nếu regex không có capture group, app lấy toàn bộ match.

### 14.5 Dùng biến extract ở step sau

Step Group 1:

```text
token = json:$.data.token
```

Step Group 2:

```bash
curl {{base_url}}/profile \
  -H 'Authorization: Bearer {{token}}'
```

### 14.6 Timing quan trọng

Biến extract từ một group chỉ chắc chắn dùng được ở group sau.

Không nên để 2 step cùng group theo kiểu:

- Step A extract token
- Step B dùng token

Vì cùng group chạy parallel. Hãy đặt Step B ở group tiếp theo.

---

## 15. API Scenario Assertions

Assertions kiểm tra response của step.

Nếu step không có assertion, pass mặc định là status `2xx/3xx`.

Nếu step có assertion, tất cả assertion phải pass.

### 15.1 Status assertion

```text
status == 200
status != 500
status >= 200
status < 400
status in 200,201,204
```

### 15.2 Body assertion

```text
body contains success
body not_contains error
```

### 15.3 Header assertion

```text
header Content-Type contains json
header X-Request-Id != ""
header X-Request-Id exists
header Cache-Control == no-cache
```

### 15.4 JSON assertion

```text
json $.data.id exists
json $.ok == true
json $.count >= 1
json $.data.name == "Nguyen Van A"
```

### 15.5 JSON path hỗ trợ

Hỗ trợ dạng đơn giản:

```text
$.data.token
$.data.items[0].id
$.data.items[-1].id      # phần tử cuối
$.users[2].email
$['full name']           # key có khoảng trắng / ký tự đặc biệt
```

Chưa hỗ trợ filter phức tạp như:

```text
$.items[?(@.id==1)]
```

### 15.6 Thời gian phản hồi và biến trong assertion

```text
time < 800                       # ms
json $.data.id == {{user_id}}    # biến environment / extract / --var đều dùng được
```

`json <path> exists` trả về FAIL (không còn là ERROR) khi path không tồn tại.

### 15.7 Khi assertion fail

Step sẽ fail và log ghi rule fail.

Nếu **Stop on fail** bật, scenario dừng sau group hiện tại.

---

## 16. Ví dụ Scenario đầy đủ

### 16.1 Login rồi gọi API song song

Group 1 - Login:

```bash
curl -X POST {{base_url}}/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"secret"}'
```

Extractors:

```text
token = json:$.data.token
```

Assertions:

```text
status == 200
json $.data.token exists
```

Group 2 - Get Profile:

```bash
curl {{base_url}}/profile \
  -H 'Authorization: Bearer {{token}}'
```

Assertions:

```text
status == 200
json $.data.id exists
```

Group 2 - Get Orders:

```bash
curl {{base_url}}/orders \
  -H 'Authorization: Bearer {{token}}'
```

Assertions:

```text
status == 200
json $.data exists
```

Group 3 - Logout:

```bash
curl -X POST {{base_url}}/logout \
  -H 'Authorization: Bearer {{token}}'
```

Assertions:

```text
status in 200,204
```

---

## 17. Tests cho từng request

Mỗi tab request có tab **✅ Tests**, chạy sau mỗi lần nhận response (với Repeat: chạy trên response cuối).

### 17.1 Assertion

Dùng đúng cú pháp của Scenario (chương 15), mỗi dòng một điều kiện, dừng ở dòng FAIL đầu tiên:

```text
status == 200
time < 1000
json $.data.id exists
```

Kết quả hiện ở tab **Tests** của response (✓ / ✗ trên nhãn tab). Status bar của request ghi `Tests PASS` / `Tests FAIL`; khi FAIL, panel tự chuyển sang tab Tests.

### 17.2 Lưu giá trị response vào environment

Dòng dạng extractor lưu giá trị vào **environment đang chọn** (giống `pm.environment.set` của Postman):

```text
token = json:$.data.token
request_id = header:X-Request-Id
```

Request sau dùng lại bằng `{{token}}`.

### 17.3 Lưu và tái sử dụng

- **➕ Collection** lưu Tests cùng request (field `extractors` / `assertions`).
- Mở request từ Collection sẽ nạp lại Tests.
- Scenario → **Import Open Tabs** chuyển Tests thành Extractors/Assertions của step.
- `python cli.py run --collection <tên>` chạy collection với Tests đã lưu.

---

## 18. Import Postman / Bruno / HAR

Collections → **⇪ Import**:

- **Postman collection / environment, HAR (file)...**: chọn file `.json` / `.har` / `.bru`.
- **Bruno collection (thư mục)...**: chọn thư mục chứa `bruno.json`.

Dữ liệu import được tạo thành collection/environment mới (trùng tên thì thêm hậu tố `(2)`), không ghi đè dữ liệu cũ. Sau khi import, app liệt kê các phần không chuyển đổi được (script JS, kiểu auth lạ, body dạng file).

| Nguồn | Hỗ trợ |
|---|---|
| Postman v2.0/v2.1 | Folder, headers, raw/urlencoded/form-data/GraphQL, bearer/basic/API key (kể cả kế thừa), biến collection, test phổ biến |
| Postman environment | Biến đang bật |
| Bruno | `.bru` requests, environments (biến `vars:secret` cần điền lại), `assert`, `vars:post-response` |
| HAR | Request XHR/fetch; cảnh báo vì HAR chứa cookie/token thật |

CLI tương đương: `python cli.py import <file|thư mục>` (thêm `--dry-run` để xem trước).

---

## 19. Chạy bằng CLI / CI

`cli.py` dùng chung engine với cửa sổ Scenario.

### 19.1 Các lệnh

| Lệnh | Mục đích |
|---|---|
| `python cli.py run ...` | Chạy scenario / collection / collection Postman-Bruno |
| `python cli.py request "curl ..."` | Gửi 1 request, body ra stdout, status/assertion ra stderr |
| `python cli.py import <path>` | Import vào dữ liệu của app |
| `python cli.py list scenarios\|environments\|collections` | Xem dữ liệu đã lưu |

### 19.2 Chọn thứ cần chạy

```bash
python cli.py run --scenario "Checkout Smoke"          # trong ~/.curl_runner/scenarios.json
python cli.py run --all                                 # tất cả scenario
python cli.py run --file ci/checkout.scenario.json      # file export (Scenario → Export Report → Scenario JSON)
python cli.py run --collection Smoke                    # collection, mỗi request 1 group tuần tự
python cli.py run --from postman_collection.json        # chạy thẳng Postman / Bruno
```

### 19.3 Biến

Thứ tự ưu tiên tăng dần:

1. Environment: `--env QA` (từ `environments.json`) hoặc `--env-file` (file của app, file JSON phẳng, hoặc export environment của Postman)
2. Biến môi trường OS `CURLRUNNER_VAR_<tên>` — dùng cho secret trên CI
3. Cột của file `--data`
4. `--var tên=giá_trị`

### 19.4 Data-driven

`--data users.csv` (CSV có dòng tiêu đề) hoặc `.json` (list object): scenario chạy 1 lần cho mỗi dòng, report ghi `Tên scenario [#n] › Step`.

### 19.5 Report và exit code

`--report` dùng nhiều lần, định dạng theo đuôi file: `.xml` (JUnit), `.html`, `.csv`, `.json`. Thư mục được tạo tự động.

| Exit code | Ý nghĩa |
|---|---|
| `0` | Tất cả step PASS |
| `1` | Có step FAIL hoặc không được chạy (do stop on fail) |
| `2` | Sai tham số / không tìm thấy file, scenario, environment |

Tuỳ chọn khác: `--no-stop-on-fail`, `-k/--insecure`, `-v/--verbose`.

### 19.6 GitHub Actions

```yaml
- run: pip install requests charset-normalizer
- run: python cli.py run --file ci/checkout.scenario.json --env-file ci/envs.json --env QA --report reports/junit.xml
  env:
    CURLRUNNER_VAR_token: ${{ secrets.API_TOKEN }}
```

---

## 20. Biến bí mật & lịch sử

### 20.1 Biến nào là bí mật

- Tên chứa `token`, `secret`, `password`/`pass`/`pwd`, `api_key`, `cookie`, `session`, `credential`, `private`... được nhận diện tự động (cột **Bí mật** hiện `🔒 auto`).
- Biến khác: double-click cột **Bí mật** trong Environment Manager để đánh dấu `🔒`.

Giá trị bí mật hiển thị `••••••`; nút **👁 Hiện giá trị** để xem/sửa.

### 20.2 Lịch sử không lưu token

Trước khi lưu History:

- Giá trị của biến bí mật → `{{tên_biến}}`, nên mở lại request vẫn chạy được.
- Token dán thẳng → `[REDACTED]`: header `Authorization`/`Cookie`/`X-Api-Key`, `-u user:pass`, `--oauth2-bearer`, query `?token=`/`?api_key=`, trường `password`/`token`/`secret` trong body JSON/form.

Nút **🔒** dưới History: bật/tắt tính năng này (mặc định bật) và **Che bí mật trong toàn bộ lịch sử hiện có**.

### 20.3 Che ở nơi khác

- Panel **Info**: giá trị bí mật hiện `••••••`.
- **AI Analyze**: giá trị bí mật được thay bằng `[REDACTED]` trước khi gửi (ngoài cơ chế redact theo tên key đã có).

### 20.4 Giới hạn

`environments.json` vẫn lưu giá trị bí mật dạng văn bản trên máy. Không commit file này; trên CI dùng `CURLRUNNER_VAR_*`.

---

## 21. Dữ liệu lưu ở đâu

App lưu dữ liệu trong:

```text
C:\Users\<user>\.curl_runner\
```

Các file chính:

| File | Nội dung |
|---|---|
| `history.json` | Lịch sử request |
| `collections.json` | Collections |
| `environments.json` | Environments |
| `scenarios.json` | API Scenarios |
| `font_settings.json` | Font settings |
| `settings.json` | Che history, danh sách biến bí mật đánh dấu thủ công |
| `*.corrupt-*.bak` | Bản sao file JSON bị hỏng (app tạo lại file mới thay vì ghi đè mất dữ liệu) |

---

## 22. Troubleshooting

### 22.1 App không chạy

Thử chạy bằng terminal để xem lỗi:

```powershell
python main.py
```

Kiểm tra dependencies:

```powershell
pip install -r requirements.txt
```

### 22.2 Curl parse lỗi

Kiểm tra:

- Curl có bắt đầu bằng `curl` không
- Quote có đóng đủ không
- Body JSON có escape đúng không
- Windows multiline dùng `^`, Linux/macOS multiline dùng `\`

### 22.3 SSL lỗi

Nếu API dev dùng self-signed certificate:

- Tắt **Verify SSL**
- Hoặc dùng curl flag `-k`

### 22.4 Response lỗi encoding

Thử:

- Bật **Auto Decode**
- Nếu vẫn lỗi, tắt Auto Decode để xem raw text

### 22.5 Scenario không truyền được token

Kiểm tra:

- Step extract token phải pass
- Step dùng token nên ở group sau
- Extractor JSON path đúng chưa
- Response có token thật không

### 22.6 Assertion JSON fail

Kiểm tra:

- Response có phải JSON hợp lệ không
- JSON path bắt đầu bằng `$`
- Array index có đúng không, ví dụ `[0]`
- Giá trị boolean dùng `true`/`false`, không phải `True`/`False`

---

## 23. Best practices cho dev/tester

### 23.1 Tách environment

Nên tạo environment riêng:

- Local
- Dev
- Staging
- Production read-only

### 23.2 Không lưu secret thật trong repo

App lưu local trong `~\.curl_runner`, không nên commit file này lên Git.

### 23.3 Dùng Scenario group rõ ràng

Gợi ý:

- Group 1: setup/login/create test data
- Group 2: các API kiểm tra parallel
- Group 3: cleanup/logout

### 23.4 Assertion nên ngắn và rõ

Tốt:

```text
status == 200
json $.data.id exists
```

Không nên bắt quá nhiều chi tiết không ổn định như timestamp chính xác.

### 23.5 Repeat dùng cẩn thận

Repeat hữu ích để test:

- cache
- rate limit
- flaky API
- performance cơ bản

Không nên dùng Repeat lớn trên production API.

---

## 24. Giới hạn hiện tại

Những phần app chưa có hoặc còn MVP:

- Chưa delay giữa step/group
- Data-driven (CSV/JSON) mới có trên CLI, chưa có trong cửa sổ Scenario
- JSON path chỉ hỗ trợ dạng cơ bản
- Parallel group chưa có per-step dependency bên trong cùng group
- Stop không huỷ request đang chạy, chỉ dừng group tiếp theo

---

## 25. Roadmap gợi ý

Các chức năng nên thêm tiếp:

1. Delay per step/group
2. Data-driven testing trong cửa sổ Scenario (CLI đã có `--data`)
3. JSON schema validation
4. OpenAPI import (Postman / Bruno / HAR đã có)
5. Per-step retry policy
6. Scenario result history
7. Nút Cancel cho request đang chạy

Xem thêm [IMPROVEMENT_ROADMAP.md](IMPROVEMENT_ROADMAP.md).
