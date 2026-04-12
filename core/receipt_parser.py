"""OCR 결과 → ReceiptData 파싱"""
import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from models.receipt_data import ReceiptData
from config import NONTAX_KEYWORDS, AI_SUBSCRIPTION_KEYWORDS


HOLIDAYS_2026 = {
    # 토/일 외 공휴일 (2026년)
    "2026-01-01", "2026-01-28", "2026-01-29", "2026-01-30",
    "2026-03-01", "2026-05-05", "2026-05-25", "2026-06-06",
    "2026-08-15", "2026-09-24", "2026-09-25", "2026-09-26",
    "2026-10-03", "2026-10-09", "2026-12-25",
}


def _is_holiday(date_str: str) -> bool:
    """날짜 문자열이 주말 또는 공휴일인지 판단"""
    if not date_str:
        return False
    try:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
            try:
                d = date.fromisoformat(date_str[:10]) if fmt == "%Y-%m-%d" else None
                if d is None:
                    import datetime
                    d = datetime.datetime.strptime(date_str[:len(fmt)], fmt).date()
                if d.weekday() >= 5:  # 토=5, 일=6
                    return True
                return date_str[:10] in HOLIDAYS_2026
            except ValueError:
                continue
    except Exception:
        pass
    return False


class ReceiptParser:
    def __init__(self, master_loader=None):
        self.master = master_loader

    def parse(self, items: list[dict], source_file: str = "unknown") -> ReceiptData:
        texts = [i["text"] for i in items]
        full = "\n".join(texts)

        def find(patterns, text=full):
            for p in patterns:
                m = re.search(p, text, re.IGNORECASE)
                if m:
                    return m.group(1).strip() if m.lastindex else m.group(0).strip()
            return None

        # 가맹점명
        merchant = None
        for item in items[:10]:
            t = item["text"].strip()
            if len(t) >= 2 and not re.match(r'^[\d\-\s\(\)]+$', t):
                if not re.search(r'사업자|대표|전화|TEL|tel', t, re.I):
                    merchant = t
                    break

        # 모든 사업자번호 추출
        all_biz_nos = re.findall(r'\d{3}-\d{2}-\d{5}', full)
        # 중복 제거 (순서 유지)
        seen = set()
        unique_biz_nos = [bn for bn in all_biz_nos if not (bn in seen or seen.add(bn))]

        # 대행사 필터 후 실거래 사업자번호 결정
        if self.master and len(unique_biz_nos) > 1:
            actual = self.master.filter_actual_biz_nos(unique_biz_nos)
        else:
            actual = unique_biz_nos
        biz_no = actual[0] if actual else (unique_biz_nos[0] if unique_biz_nos else None)

        # 승인번호
        approval_no = find([
            r'승인[번호\s]*[:：]?\s*(\d{6,10})',
            r'승인\s+(\d{6,10})',
            r'[Aa]pproval\s*[Nn]o\.?\s*[:：]?\s*(\d{6,10})',
        ])

        # 거래일시
        date_str = find([
            r'(\d{4}[./\-]\d{2}[./\-]\d{2}[\s\-]+\d{2}:\d{2}(?::\d{2})?)',
            r'(\d{4}[./\-]\d{2}[./\-]\d{2})',
            r'거래일시\s*[:：]?\s*(\d{8}\s*\d{2}:\d{2})',
        ])

        # 거래 시각 추출
        transaction_time = None
        t_match = re.search(r'(\d{2}:\d{2})(?::\d{2})?', full)
        if t_match:
            transaction_time = t_match.group(1)

        # 합계금액
        total_str = find([
            r'합\s*계\s*[:：]?\s*([\d,]+)\s*원',
            r'총\s*금\s*액\s*[:：]?\s*([\d,]+)\s*원',
            r'결제금액\s*[:：]?\s*([\d,]+)\s*원',
            r'청구금액\s*[:：]?\s*([\d,]+)\s*원',
        ])
        total = int(total_str.replace(",", "")) if total_str else None

        # 부가세
        vat_str = find([
            r'부가세\s*[:：]?\s*([\d,]+)\s*원?',
            r'세\s*액\s*[:：]?\s*([\d,]+)\s*원?',
            r'VAT\s*[:：]?\s*([\d,]+)\s*원?',
        ])
        vat = int(vat_str.replace(",", "")) if vat_str else None

        # 공급가액
        supply_str = find([
            r'공급가액\s*[:：]?\s*([\d,]+)\s*원?',
            r'공급\s*금\s*액\s*[:：]?\s*([\d,]+)\s*원?',
        ])
        supply = int(supply_str.replace(",", "")) if supply_str else None

        # 카드번호
        card_no = find([
            r'(\d{4}[-\s*]+\d{4}[-\s*]+[\d*]{4}[-\s*]+[\d*]{4})',
            r'카드번호\s*[:：]?\s*([\d\-\*\s]{13,19})',
        ])

        # 불공제 키워드
        nontax_found = [kw for kw in NONTAX_KEYWORDS if re.search(kw, full, re.IGNORECASE)]
        ai_found = [kw for kw in AI_SUBSCRIPTION_KEYWORDS if re.search(kw, full, re.IGNORECASE)]
        nontax_keywords = list(set(nontax_found + ai_found))

        # 업체 유형
        is_megamart = bool(re.search(r'메가마트|판도라', full, re.IGNORECASE))
        is_openmarket = bool(re.search(
            r'쿠팡|11번가|G마켓|옥션|위메프|티몬|인터파크|네이버쇼핑|카카오쇼핑', full, re.IGNORECASE
        ))
        is_gift_shop = bool(re.search(r'상품권|백화점|마트|면세점', full, re.IGNORECASE))
        is_taxi = bool(re.search(r'택시|카카오T|티머니|타다|KM택시', full, re.IGNORECASE))
        is_holiday = _is_holiday(date_str or "")

        return ReceiptData(
            source_file=source_file,
            merchant=merchant,
            biz_no=biz_no,
            all_biz_nos=unique_biz_nos,
            approval_no=approval_no,
            date=date_str,
            transaction_time=transaction_time,
            total=total,
            vat=vat,
            supply=supply,
            card_no=card_no,
            nontax_keywords=nontax_keywords,
            is_megamart=is_megamart,
            is_openmarket=is_openmarket,
            is_gift_shop=is_gift_shop,
            is_taxi=is_taxi,
            is_holiday=is_holiday,
            raw_text=full,
        )

    def from_json_file(self, path: str | Path) -> ReceiptData:
        """OCR 없이 mock JSON 파싱 결과 직접 로드"""
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return ReceiptData(
            source_file=d.get("source_file", str(path)),
            merchant=d.get("merchant"),
            biz_no=d.get("biz_no"),
            all_biz_nos=d.get("all_biz_nos", []),
            approval_no=d.get("approval_no"),
            date=d.get("date"),
            transaction_time=d.get("transaction_time"),
            total=d.get("total"),
            vat=d.get("vat"),
            supply=d.get("supply"),
            card_no=d.get("card_no"),
            nontax_keywords=d.get("nontax_keywords", []),
            is_megamart=d.get("is_megamart", False),
            is_openmarket=d.get("is_openmarket", False),
            is_gift_shop=d.get("is_gift_shop", False),
            is_taxi=d.get("is_taxi", False),
            is_holiday=d.get("is_holiday", False),
            raw_text=d.get("raw_text", ""),
        )
