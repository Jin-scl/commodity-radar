"""pytest 公共：把项目根加到 sys.path，让 `from src.xxx import` 生效。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
