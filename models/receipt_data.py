"""OCR로 추출한 영수증 데이터 구조"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReceiptData:
    source_file: str
    merchant: Optional[str]
    biz_no: Optional[str]           # 대행사 필터 후 확정된 실거래 사업자번호
    all_biz_nos: list = field(default_factory=list)  # 영수증 내 모든 사업자번호
    approval_no: Optional[str] = None
    date: Optional[str] = None
    transaction_time: Optional[str] = None  # "HH:MM" 형식 (택시비 심야 판단)
    total: Optional[int] = None
    vat: Optional[int] = None
    supply: Optional[int] = None
    card_no: Optional[str] = None
    nontax_keywords: list = field(default_factory=list)
    is_megamart: bool = False
    is_openmarket: bool = False
    is_gift_shop: bool = False
    is_taxi: bool = False
    is_holiday: bool = False
    raw_text: str = ""

    @classmethod
    def empty(cls, source_file: str = "unknown") -> "ReceiptData":
        return cls(source_file=source_file, merchant=None, biz_no=None)
