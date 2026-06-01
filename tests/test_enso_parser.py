"""NOAA Niño 3.4 周度文件解析单测。

P1 修复：之前用 parts[-1] 取最后一列（实际是 Niño4 SSTA），现在按位置取 Niño34 SSTA。
"""
from src.fetchers.enso import _parse_nino34_weekly


def test_parse_extracts_nino34_not_nino4():
    """关键用例：13MAY2026 行 Niño34=0.9, Niño4=1.0；
    如果取错列会返回 1.0，正确实现应返回 0.9。"""
    text = """ Weekly SST data starts week centered on 2Sept1981

                Nino1+2      Nino3        Nino34        Nino4
 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 13MAY2026     26.4 1.8     28.3 1.1     28.8 0.9     29.8 1.0
"""
    result = _parse_nino34_weekly(text)
    assert result is not None
    anom, date_str = result
    assert anom == 0.9, f"expected 0.9 (Niño34), got {anom} (likely Niño4)"
    assert date_str == "2026-05-13"


def test_parse_handles_concatenated_columns():
    """1981 年代行 SST 和 SSTA 之间无空格，必须用正则提取数字。
    示例: '02SEP1981     20.6-0.1     24.8-0.1     26.5-0.2     28.3-0.3'
    Niño34 SSTA = -0.2"""
    text = """                Nino1+2      Nino3        Nino34        Nino4
 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 02SEP1981     20.6-0.1     24.8-0.1     26.5-0.2     28.3-0.3
"""
    result = _parse_nino34_weekly(text)
    assert result is not None
    anom, _ = result
    assert anom == -0.2, f"expected -0.2 (Niño34 SSTA), got {anom}"


def test_parse_returns_last_data_row():
    """有多行数据时返回最后一行（最新一周）。"""
    text = """                Nino1+2      Nino3        Nino34        Nino4
 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 20MAY2026     26.4 2.1     28.3 1.2     28.8 1.0     29.8 1.0
 27MAY2026     26.2 2.2     28.3 1.3     28.8 1.1     29.9 1.2
"""
    result = _parse_nino34_weekly(text)
    assert result is not None
    anom, date_str = result
    assert anom == 1.1
    assert date_str == "2026-05-27"


def test_parse_skips_garbage_lines():
    """非数据行应被跳过，不抛异常。"""
    text = """ Weekly SST data starts week centered on 2Sept1981

 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 (empty rows for test)
 27MAY2026     26.2 2.2     28.3 1.3     28.8 1.0     29.9 1.1
 missing date row 1.0 2.0
"""
    result = _parse_nino34_weekly(text)
    assert result is not None
    anom, date_str = result
    assert anom == 1.0
    assert date_str == "2026-05-27"
