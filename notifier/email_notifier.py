"""위반 사항 이메일 통보 (mock 콘솔 출력 또는 SMTP 실제 발송)"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from models.check_result import CheckResult, CheckStatus

STATUS_ICON = {
    CheckStatus.FAIL: "❌",
    CheckStatus.WARN: "⚠️",
    CheckStatus.OK:   "✅",
    CheckStatus.INFO: "ℹ️",
    CheckStatus.SKIP: "⏭️",
}

CATEGORY_ORDER = ["부가세", "부서코드", "계정과목", "원천세", "이월처리", "증빙첨부", "택시비", "휴일사용", "결재권자"]


class EmailNotifier:
    def __init__(self, use_mock: bool = True, smtp_config: dict = None):
        self.use_mock = use_mock
        self.smtp_config = smtp_config or {}

    def notify(self, result: CheckResult) -> None:
        subject = f"[신용카드 점검] {result.email_id} 위반 사항 통보"
        body = self._build_body(result)
        if self.use_mock:
            self._mock_output(result.submitter_email, subject, body)
        else:
            self._send_smtp(result.submitter_email, subject, body)

    def _build_body(self, result: CheckResult) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            f"안녕하세요, {result.submitter_name}님.",
            "",
            f"신용카드 결제 점검 결과 아래와 같이 위반/주의 사항이 확인되었습니다.",
            f"원본 이메일: {result.subject}  |  점검일시: {now}",
            "",
            "─" * 60,
        ]

        fail_warns = result.fail_and_warn()
        # 카테고리별 그룹화
        by_category: dict[str, list] = {}
        for v in fail_warns:
            by_category.setdefault(v.category, []).append(v)

        for cat in CATEGORY_ORDER:
            if cat not in by_category:
                continue
            lines.append(f"\n【{cat}】")
            for v in by_category[cat]:
                icon = STATUS_ICON.get(v.status, "  ")
                lines.append(f"  {icon} [규칙 {v.rule_no:02d}] {v.check_name}")
                lines.append(f"       {v.message}")

        # CATEGORY_ORDER에 없는 나머지
        for cat, vs in by_category.items():
            if cat in CATEGORY_ORDER:
                continue
            lines.append(f"\n【{cat}】")
            for v in vs:
                icon = STATUS_ICON.get(v.status, "  ")
                lines.append(f"  {icon} [규칙 {v.rule_no:02d}] {v.check_name}")
                lines.append(f"       {v.message}")

        summary = result.summary()
        lines += [
            "",
            "─" * 60,
            f"점검 요약: ✅ 정상 {summary['OK']}건  ⚠️ 주의 {summary['WARN']}건  ❌ 실패 {summary['FAIL']}건",
            "",
            "위반/주의 사항을 수정하여 재상신하여 주시기 바랍니다.",
            "문의사항은 담당자에게 연락해 주세요.",
        ]
        return "\n".join(lines)

    def _mock_output(self, to_addr: str, subject: str, body: str) -> None:
        print("\n" + "=" * 60)
        print(f"[MOCK EMAIL 발송]")
        print(f"  To     : {to_addr}")
        print(f"  Subject: {subject}")
        print("─" * 60)
        print(body)
        print("=" * 60 + "\n")

    def _send_smtp(self, to_addr: str, subject: str, body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_config.get("from", "checker@company.com")
        msg["To"] = to_addr
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP(self.smtp_config["host"], self.smtp_config["port"]) as s:
            s.starttls()
            s.login(self.smtp_config["user"], self.smtp_config["password"])
            s.sendmail(msg["From"], [to_addr], msg.as_string())
        print(f"[EMAIL 발송 완료] → {to_addr}")
