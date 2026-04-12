"""이메일 단위 처리 결과를 checker results.csv에 기록"""
import csv
from pathlib import Path

from models.email_data import EmailData
from models.receipt_data import ReceiptData
from models.check_result import CheckResult, CheckStatus

RESULTS_FILE = Path(__file__).parent.parent / "logs" / "checker results.csv"

RULE_COLUMNS = [
    ("R01", "R01_부가세금액"),
    ("R02", "R02_사업자번호"),
    ("R03", "R03_불공제"),
    ("R04", "R04_부서코드"),
    ("R05", "R05_계정과목"),
    ("R06", "R06_원천세_선물"),
    ("R07", "R07_원천세_상품권"),
    ("R08", "R08_이월처리"),
    ("R09", "R09_다인식대"),
    ("R10", "R10_메가마트"),
    ("R11", "R11_오픈마켓"),
    ("R12", "R12_품의서"),
    ("R13", "R13_택시비"),
    ("R14", "R14_휴일사용"),
    ("R15", "R15_결재권자"),
]

HEADER = (
    ["timestamp", "이메일제목", "기안자", "삼성전표번호",
     "NERP_업체명", "NERP_사업자번호", "NERP_결제금액", "NERP_부가세", "NERP_계정과목",
     "영수증_가맹점명", "영수증_사업자번호", "영수증_부가세"]
    + [col for _, col in RULE_COLUMNS]
    + ["점검결과 회신", "점검결과 회신 내용"]
)


def _rule_status(result: CheckResult, rule_no: int) -> str:
    """해당 규칙 번호의 최악 상태 반환 (FAIL > WARN > OK > 빈칸)"""
    matched = [v for v in result.violations if v.rule_no == rule_no]
    if not matched:
        return ""
    priority = {CheckStatus.FAIL: 3, CheckStatus.WARN: 2, CheckStatus.OK: 1}
    worst = max(matched, key=lambda v: priority.get(v.status, 0))
    if worst.status in (CheckStatus.OK,):
        return "OK"
    return worst.status.value


def _notify_content(result: CheckResult) -> str:
    """FAIL/WARN 항목 요약 문자열"""
    parts = []
    for v in sorted(result.fail_and_warn(), key=lambda x: x.rule_no):
        parts.append(f"[R{v.rule_no:02d}]{v.message}")
    return " / ".join(parts)


def write_result(timestamp: str,
                 email: EmailData,
                 receipt: ReceiptData | None,
                 result: CheckResult,
                 notified: bool) -> None:
    """결과 1행을 checker results.csv에 추가"""
    RESULTS_FILE.parent.mkdir(exist_ok=True)

    write_header = not RESULTS_FILE.exists() or RESULTS_FILE.stat().st_size == 0

    # 기안자: 이름(knox_id)
    submitter = f"{email.submitter.name}({email.submitter.knox_id})"

    # 규칙별 상태
    rule_statuses = [_rule_status(result, int(no[1:])) for no, _ in RULE_COLUMNS]

    # 점검결과 회신 Y/N
    has_violation = result.has_violation()
    notify_yn = "Y" if notified else "N"
    notify_content = _notify_content(result) if has_violation else ""

    row = (
        [timestamp, email.subject, submitter, email.samsung_doc_no,
         email.payment.merchant_name,
         email.payment.biz_no,
         email.payment.total_amount,
         email.payment.vat_amount,
         email.accounting.account_name,
         receipt.merchant if receipt else "",
         receipt.biz_no if receipt else "",
         receipt.vat if receipt else ""]
        + rule_statuses
        + [notify_yn, notify_content]
    )

    with open(RESULTS_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(HEADER)
        writer.writerow(row)
