"""이메일 단위 처리 결과를 checker results.csv 및 TXT 리포트로 기록"""
import csv
from datetime import datetime
from pathlib import Path

from models.email_data import EmailData
from models.receipt_data import ReceiptData
from models.check_result import CheckResult, CheckStatus

RESULTS_FILE = Path(__file__).parent.parent / "logs" / "checker results.csv"
REPORTS_DIR  = Path(__file__).parent.parent / "logs" / "reports"

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
    + ["TXT저장", "점검결과 요약"]
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


def _summary_content(result: CheckResult) -> str:
    """FAIL/WARN 항목 요약 문자열 (CSV용)"""
    parts = []
    for v in sorted(result.fail_and_warn(), key=lambda x: x.rule_no):
        parts.append(f"[R{v.rule_no:02d}]{v.message}")
    return " / ".join(parts)


# ── TXT 리포트 ────────────────────────────────────────────────────────────────

def write_txt_report(email: EmailData,
                     receipt: ReceiptData | None,
                     result: CheckResult) -> Path:
    """점검 결과를 TXT 파일로 저장하고 파일 경로를 반환.

    저장 위치: logs/reports/{email_id}.txt
    내용: 기본 정보 + 오류(FAIL) + 보완필요(WARN)
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = email.submitted_at[:10].replace("-", "")  # YYYYMMDD (이메일 수신일)
    txt_path = REPORTS_DIR / f"{date_str}_{email.submitter.knox_id}_{email.samsung_doc_no}.txt"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = result.summary()
    fails  = [v for v in result.violations if v.status == CheckStatus.FAIL]
    warns  = [v for v in result.violations if v.status == CheckStatus.WARN]

    lines = [
        "=" * 60,
        "[신용카드 결제 점검 결과]",
        "=" * 60,
        f"원본 이메일 : {result.subject}",
        f"기안자      : {result.submitter_name} ({email.submitter.knox_id})",
        f"업체명      : {email.payment.merchant_name}",
        f"결제금액    : {email.payment.total_amount:,}원  (부가세 {email.payment.vat_amount:,}원)",
        f"계정과목    : {email.accounting.account_name}",
        f"점검일시    : {now}",
        "-" * 60,
        f"점검 요약   : ✅ 정상 {summary['OK']}건  ⚠️  보완필요 {summary['WARN']}건  ❌ 오류 {summary['FAIL']}건",
        "-" * 60,
    ]

    if fails:
        lines.append(f"\n[오류 항목] {len(fails)}건 — 수정 후 재상신 필요")
        for v in sorted(fails, key=lambda x: x.rule_no):
            lines.append(f"  ❌ [R{v.rule_no:02d}] {v.check_name}")
            lines.append(f"       {v.message}")

    if warns:
        lines.append(f"\n[보완 필요] {len(warns)}건 — 확인 및 조치 권고")
        for v in sorted(warns, key=lambda x: x.rule_no):
            lines.append(f"  ⚠️  [R{v.rule_no:02d}] {v.check_name}")
            lines.append(f"       {v.message}")

    if not fails and not warns:
        lines.append("\n이상 없음 — 모든 점검 항목을 통과하였습니다.")

    lines.append("\n" + "=" * 60)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return txt_path


# ── CSV 결과 기록 ──────────────────────────────────────────────────────────────

def write_result(timestamp: str,
                 email: EmailData,
                 receipt: ReceiptData | None,
                 result: CheckResult,
                 txt_saved: bool) -> None:
    """결과 1행을 checker results.csv에 추가"""
    RESULTS_FILE.parent.mkdir(exist_ok=True)

    write_header = not RESULTS_FILE.exists() or RESULTS_FILE.stat().st_size == 0

    submitter    = f"{email.submitter.name}({email.submitter.knox_id})"
    rule_statuses = [_rule_status(result, int(no[1:])) for no, _ in RULE_COLUMNS]
    txt_yn       = "Y" if txt_saved else "N"
    summary_text = _summary_content(result) if result.has_violation() else ""

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
        + [txt_yn, summary_text]
    )

    with open(RESULTS_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(HEADER)
        writer.writerow(row)
