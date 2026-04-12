"""로깅 설정 모듈
- 콘솔: INFO 이상 (색상 적용)
- 파일: DEBUG 이상 (logs/checker.csv, 전체 누적 CSV)

CSV 컬럼: timestamp, level, step, rule_no, category, message
"""
import csv
import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

CSV_LOG_FILE = LOG_DIR / "checker logs.csv"
CSV_HEADER = ["timestamp", "level", "step", "rule_no", "category", "message"]

# ── 색상 코드 (콘솔 전용) ────────────────────────────────────────────────
_COLORS = {
    "DEBUG":    "\033[90m",
    "INFO":     "\033[0m",
    "WARNING":  "\033[93m",
    "ERROR":    "\033[91m",
    "CRITICAL": "\033[95m",
}
_RESET = "\033[0m"


def _parse_message(msg: str) -> tuple[str, str, str]:
    """메시지에서 step, rule_no, category 추출
    예) '[R03] FAIL [부가세] 부가세 불공제...' → ('CHECK', '3', '부가세')
        '[PARSE] 이메일 파싱 완료'              → ('PARSE', '', '')
    """
    import re
    # [Rxx] 패턴 (규칙 번호 포함)
    m = re.match(r'\[R(\d+)\]\s+\w+\s+\[([^\]]+)\]\s*(.*)', msg)
    if m:
        return "CHECK", m.group(1), m.group(2)

    # [STEP] 패턴
    m = re.match(r'\[([A-Z_]+)\]\s*(.*)', msg)
    if m:
        return m.group(1), "", ""

    return "", "", ""


class _CSVHandler(logging.Handler):
    """각 로그 레코드를 CSV 한 행으로 저장"""

    def __init__(self, filepath: Path):
        super().__init__()
        self._filepath = filepath
        # 헤더가 없는 새 파일이면 헤더 작성
        if not filepath.exists() or filepath.stat().st_size == 0:
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow(CSV_HEADER)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            step, rule_no, category = _parse_message(msg)
            timestamp = self.formatter.formatTime(record, "%Y-%m-%d %H:%M:%S")
            with open(self._filepath, "a", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerow([
                    timestamp,
                    record.levelname,
                    step,
                    rule_no,
                    category,
                    msg,
                ])
        except Exception:
            self.handleError(record)


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelname, "")
        msg = super().format(record)
        return f"{color}{msg}{_RESET}"


def get_logger(name: str = "checker") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # 이미 초기화됨

    logger.setLevel(logging.DEBUG)

    # ── 콘솔 핸들러 (INFO+) ────────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(_ColorFormatter(
        fmt="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(ch)

    # ── CSV 파일 핸들러 (DEBUG+) ───────────────────────────────────────
    csv_handler = _CSVHandler(CSV_LOG_FILE)
    csv_handler.setLevel(logging.DEBUG)
    csv_handler.setFormatter(logging.Formatter(datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(csv_handler)

    return logger
