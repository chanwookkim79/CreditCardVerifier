"""이메일 데이터 구조 정의"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Submitter:
    employee_id: str       # 사번 (8자리, 앞자리 0 포함)
    knox_id: str           # Knox ID / 사내 계정 ID
    name: str
    department: str
    department_code: str
    email: str


@dataclass
class Approver:
    name: str
    department: str
    department_code: str


@dataclass
class Payment:
    approval_no: str
    card_no_masked: str
    merchant_name: str
    biz_no: str            # 이메일에 기입된 사업자번호
    payment_date: str      # "YYYY-MM-DD"
    posting_date: str      # SAP Posting date
    document_date: str     # SAP Document date (= 실결제일)
    total_amount: int
    vat_amount: int
    supply_amount: int


@dataclass
class Accounting:
    account_code: str
    account_name: str      # 전체 계정명 (예: "복리후생비-기타-기타")
    origin_cost_center: str    # 발생부서 코드
    assigned_cost_center: str  # 비용귀속부서 코드
    tax_code: str              # SAP 세금 코드
    nontax_reason: str         # 불공제 사유
    withholding_tax_code: Optional[str]  # 원천세 코드 (1G/1Q/2C/5B 등)
    industry_code: str         # 업종 코드 (상품권 판단 등)


@dataclass
class GiftInfo:
    is_gift: bool
    unit_price: Optional[int]           # 품목당 단가
    recipients: list = field(default_factory=list)
    # recipients 항목: {"employee_id": str, "name": str, "rank": str}


@dataclass
class Attachment:
    filename: str
    type: str  # 'receipt_image' | 'withholding_list' | 'carryover_doc' | 'multi_meal_form' | 'opinion_doc' | 'other'
    withholding_tax_list_included: bool = False


@dataclass
class EmailData:
    email_id: str
    subject: str           # 이메일 제목
    samsung_doc_no: str    # 삼성 전표 번호 (형식: DJ0120260227BA000074, 중복 점검 키)
    submitted_at: str
    submitter: Submitter
    approver: Approver
    payment: Payment
    accounting: Accounting
    memo: str
    gift_info: GiftInfo
    attachments: list
    opinion: dict = field(default_factory=dict)

    def has_attachment_type(self, att_type: str) -> bool:
        return any(a.type == att_type for a in self.attachments)

    def has_receipt_image(self) -> bool:
        return self.has_attachment_type("receipt_image")
