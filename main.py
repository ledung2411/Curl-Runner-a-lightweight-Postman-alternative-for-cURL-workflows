#!/usr/bin/env python3
"""
main.py — Entry point cho Curl Runner

Chạy   : python main.py
Đóng gói: python -m PyInstaller --onefile --noconsole --name CurlRunner main.py
"""

import sys

if sys.version_info < (3, 10):
    sys.exit(
        "Curl Runner cần Python 3.10 trở lên (đang chạy Python %d.%d).\n"
        "Cài Python 3.12: winget install -e --id Python.Python.3.12  (hoặc https://www.python.org/downloads/)\n"
        "Rồi chạy: py -3.12 -m pip install -r requirements.txt  và  py -3.12 main.py" % sys.version_info[:2]
    )

from app import CurlRunnerApp  # noqa: E402

if __name__ == "__main__":
    app = CurlRunnerApp()
    app.mainloop()
