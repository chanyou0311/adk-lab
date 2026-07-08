"""tests から eval/ 配下のモジュール (tasks 等) を import できるようにする。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
