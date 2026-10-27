# store.py — Lưu/đọc dữ liệu (history, collections, environments)
# type: ignore
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

DATA_DIR  = Path(os.path.expanduser("~")) / ".curl_runner"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HIST_FILE = DATA_DIR / "history.json"
COLL_FILE = DATA_DIR / "collections.json"
ENV_FILE  = DATA_DIR / "environments.json"
SCEN_FILE = DATA_DIR / "scenarios.json"


def _backup_corrupt_file(path: Path) -> None:
    """Giữ lại bản sao file hỏng để lần save tiếp theo không xoá mất dữ liệu cũ."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        path.replace(path.with_name(f"{path.name}.corrupt-{stamp}.bak"))
    except OSError:
        pass


def load(path: Path, default):
    """Đọc file JSON, trả về default nếu chưa có file hoặc file hỏng."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except UnicodeDecodeError:
        _backup_corrupt_file(path)
        return default
    except OSError:
        return default   # file bị khoá / không có quyền: không động vào file
    try:
        data = json.loads(text)
    except ValueError:
        _backup_corrupt_file(path)
        return default
    if default is not None and not isinstance(data, type(default)):
        _backup_corrupt_file(path)
        return default
    return data


def save(path: Path, data) -> None:
    """Ghi dữ liệu ra file JSON một cách nguyên tử (ghi file tạm rồi thay thế)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ── Convenience wrappers ──────────────────────
def load_history() -> list:
    return load(HIST_FILE, [])

def save_history(data: list) -> None:
    save(HIST_FILE, data)

def load_collections() -> dict:
    return load(COLL_FILE, {})

def save_collections(data: dict) -> None:
    save(COLL_FILE, data)

def load_environments() -> dict:
    return load(ENV_FILE, {"Default": {}}) or {"Default": {}}

def save_environments(data: dict) -> None:
    save(ENV_FILE, data)

def load_scenarios() -> list:
    return load(SCEN_FILE, [])

def save_scenarios(data: list) -> None:
    save(SCEN_FILE, data)
