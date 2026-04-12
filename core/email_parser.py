"""이메일 JSON 파싱 → EmailData 객체 변환"""
import json
from pathlib import Path
from models import EmailData, Submitter, Approver, Payment, Accounting, GiftInfo, Attachment


class EmailParser:
    def parse_json_file(self, path: str | Path) -> EmailData:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return self.parse_json(data)

    def parse_json(self, data: dict) -> EmailData:
        s = data["submitter"]
        submitter = Submitter(
            employee_id=str(s.get("employee_id", "")).strip().zfill(8),
            knox_id=s.get("knox_id", ""),
            name=s.get("name", ""),
            department=s.get("department", ""),
            department_code=s.get("department_code", ""),
            email=s.get("email", ""),
        )

        a = data["approver"]
        approver = Approver(
            name=a.get("name", ""),
            department=a.get("department", ""),
            department_code=a.get("department_code", ""),
        )

        p = data["payment"]
        payment = Payment(
            approval_no=str(p.get("approval_no", "")),
            card_no_masked=p.get("card_no_masked", ""),
            merchant_name=p.get("merchant_name", ""),
            biz_no=p.get("biz_no", ""),
            payment_date=p.get("payment_date", ""),
            posting_date=p.get("posting_date", ""),
            document_date=p.get("document_date", ""),
            total_amount=int(p.get("total_amount", 0)),
            vat_amount=int(p.get("vat_amount", 0)),
            supply_amount=int(p.get("supply_amount", 0)),
        )

        ac = data["accounting"]
        accounting = Accounting(
            account_code=ac.get("account_code", ""),
            account_name=ac.get("account_name", ""),
            origin_cost_center=ac.get("origin_cost_center", ""),
            assigned_cost_center=ac.get("assigned_cost_center", ""),
            tax_code=ac.get("tax_code", ""),
            nontax_reason=ac.get("nontax_reason", ""),
            withholding_tax_code=ac.get("withholding_tax_code"),
            industry_code=ac.get("industry_code", ""),
        )

        gi = data.get("gift_info", {})
        gift_info = GiftInfo(
            is_gift=bool(gi.get("is_gift", False)),
            unit_price=gi.get("unit_price"),
            recipients=gi.get("recipients", []),
        )

        attachments = [
            Attachment(
                filename=att.get("filename", ""),
                type=att.get("type", "other"),
                withholding_tax_list_included=att.get("withholding_tax_list_included", False),
            )
            for att in data.get("attachments", [])
        ]

        # subject 없으면 업체명+금액으로 자동 생성
        subject = data.get("subject") or \
            f"[결제승인요청] {payment.merchant_name} {payment.total_amount:,}원"

        return EmailData(
            email_id=data.get("email_id", ""),
            subject=subject,
            samsung_doc_no=data.get("samsung_doc_no", ""),
            submitted_at=data.get("submitted_at", ""),
            submitter=submitter,
            approver=approver,
            payment=payment,
            accounting=accounting,
            memo=data.get("memo", ""),
            gift_info=gift_info,
            attachments=attachments,
            opinion=data.get("opinion", {}),
        )
