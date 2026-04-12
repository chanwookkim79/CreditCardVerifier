"""이메일 데이터 ↔ 영수증 OCR 결과 교차 검증 (점검규칙 적용)"""
import re
from typing import Optional

from models.email_data import EmailData
from models.receipt_data import ReceiptData
from models.check_result import Violation, CheckStatus
from config import (
    VAT_TOLERANCE, TAXI_MAX_AMOUNT, MULTI_MEAL_MIN,
    GIFT_WITHHOLDING_MIN, OPINION_REQUIRED_ACCOUNTS,
    RANK_TO_WITHHOLDING_CODE, AI_SUBSCRIPTION_KEYWORDS,
)


def _v(rule_no, category, check_name, status, message,
        email_field=None, receipt_field=None) -> Violation:
    return Violation(
        rule_no=rule_no,
        category=category,
        check_name=check_name,
        status=CheckStatus(status),
        message=message,
        email_field=email_field,
        receipt_field=receipt_field,
    )


class CrossValidator:
    def __init__(self, master_loader=None):
        self.master = master_loader

    def validate(self, email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]:
        result = []
        result += self._check_vat(email, receipt)
        result += self._check_biz_no(email, receipt)
        result += self._check_nontax(email, receipt)
        result += self._check_dept_code(email)
        result += self._check_account(email)
        result += self._check_withholding_tax(email, receipt)
        result += self._check_carryover(email)
        result += self._check_attachments(email, receipt)
        result += self._check_taxi(email, receipt)
        result += self._check_holiday(email, receipt)
        result += self._check_approver(email)
        return result

    # ─────────────────────────────────────────────────────────────────────
    # R1: 부가세 금액 일치 여부
    # ─────────────────────────────────────────────────────────────────────
    def _check_vat(self, email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]:
        if receipt is None:
            return [_v(1, "부가세", "부가세 금액 확인", "WARN",
                       "영수증 없음 - 부가세 금액 수동 확인 필요")]
        if receipt.vat is None:
            return [_v(1, "부가세", "부가세 금액 확인", "WARN",
                       "영수증에서 부가세 금액을 추출하지 못함 - 수동 확인 필요",
                       receipt_field="vat")]
        diff = abs(email.payment.vat_amount - receipt.vat)
        if diff <= VAT_TOLERANCE:
            return [_v(1, "부가세", "부가세 금액 확인", "OK",
                       f"이메일 {email.payment.vat_amount:,}원 ↔ 영수증 {receipt.vat:,}원 (차이 {diff}원)")]
        return [_v(1, "부가세", "부가세 금액 확인", "FAIL",
                   f"부가세 불일치: 이메일 {email.payment.vat_amount:,}원 ↔ 영수증 {receipt.vat:,}원 (차이 {diff}원, 허용 {VAT_TOLERANCE}원)",
                   email_field="payment.vat_amount", receipt_field="vat")]

    # ─────────────────────────────────────────────────────────────────────
    # R2: 실거래 사업자번호 일치 여부
    # ─────────────────────────────────────────────────────────────────────
    def _check_biz_no(self, email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]:
        if receipt is None:
            return [_v(2, "부가세", "실거래사업자번호 확인", "WARN",
                       "영수증 없음 - 사업자번호 수동 확인 필요")]
        if not receipt.biz_no:
            return [_v(2, "부가세", "실거래사업자번호 확인", "WARN",
                       "영수증에서 사업자번호를 추출하지 못함",
                       receipt_field="biz_no")]
        email_bn = email.payment.biz_no.replace("-", "").strip()
        receipt_bn = receipt.biz_no.replace("-", "").strip()
        if email_bn == receipt_bn:
            return [_v(2, "부가세", "실거래사업자번호 확인", "OK",
                       f"사업자번호 일치: {receipt.biz_no}")]
        note = ""
        if len(receipt.all_biz_nos) > 1:
            note = f" (영수증 내 전체 사업자번호: {', '.join(receipt.all_biz_nos)})"
        return [_v(2, "부가세", "실거래사업자번호 확인", "FAIL",
                   f"실거래사업자번호 불일치: 이메일 {email.payment.biz_no} ↔ 영수증 {receipt.biz_no}{note}",
                   email_field="payment.biz_no", receipt_field="biz_no")]

    # ─────────────────────────────────────────────────────────────────────
    # R3: 부가세 불공제 항목 점검
    # ─────────────────────────────────────────────────────────────────────
    def _check_nontax(self, email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]:
        results = []
        keywords = receipt.nontax_keywords if receipt else []

        # AI 구독 별도 처리
        ai_found = [kw for kw in AI_SUBSCRIPTION_KEYWORDS
                    if any(kw.lower() in k.lower() for k in keywords)]
        other_found = [kw for kw in keywords
                       if not any(kw.lower() in ai.lower() for ai in AI_SUBSCRIPTION_KEYWORDS)]

        if other_found:
            nontax_reason = email.accounting.nontax_reason.replace(" ", "")
            if "해당사항없음" in nontax_reason or nontax_reason == "":
                results.append(_v(3, "부가세", "부가세 불공제 항목 점검", "FAIL",
                    f"불공제 항목 발견({', '.join(other_found)})하지만 불공제 사유가 '해당사항없음'임 - 불공제 처리 필요",
                    email_field="accounting.nontax_reason", receipt_field="nontax_keywords"))
            else:
                results.append(_v(3, "부가세", "부가세 불공제 항목 점검", "OK",
                    f"불공제 항목({', '.join(other_found)}) 및 불공제 사유 확인됨"))

        # 선물 처리
        if email.gift_info.is_gift or "선물" in email.accounting.nontax_reason:
            if not email.accounting.withholding_tax_code:
                results.append(_v(3, "부가세", "선물 원천세 코드 확인", "FAIL",
                    "선물 구입 건: 원천세 코드가 이메일에 없음",
                    email_field="accounting.withholding_tax_code"))
            else:
                results.append(_v(3, "부가세", "선물 원천세 코드 확인", "OK",
                    f"선물 건 원천세 코드 확인: {email.accounting.withholding_tax_code}"))

        # AI 구독 처리
        if ai_found:
            acc = email.accounting.account_name
            reason = email.accounting.nontax_reason
            acc_ok = "지급수수료-기타" in acc
            reason_ok = "기타" in reason
            if acc_ok and reason_ok:
                results.append(_v(3, "부가세", "AI 서비스 구독 계정 확인", "OK",
                    f"AI 구독({', '.join(ai_found)}): 계정/불공제 사유 적절"))
            else:
                msg_parts = []
                if not acc_ok:
                    msg_parts.append(f"계정이 '지급수수료-기타'가 아님 (현재: {acc})")
                if not reason_ok:
                    msg_parts.append(f"불공제 사유가 '기타'가 아님 (현재: {reason})")
                results.append(_v(3, "부가세", "AI 서비스 구독 계정 확인", "FAIL",
                    f"AI 구독({', '.join(ai_found)}): " + "; ".join(msg_parts),
                    email_field="accounting.account_name"))

        if not results:
            results.append(_v(3, "부가세", "부가세 불공제 항목 점검", "OK", "불공제 해당 항목 없음"))
        return results

    # ─────────────────────────────────────────────────────────────────────
    # R4: 부서코드 일치
    # ─────────────────────────────────────────────────────────────────────
    def _check_dept_code(self, email: EmailData) -> list[Violation]:
        results = []
        ori = email.accounting.origin_cost_center
        asgn = email.accounting.assigned_cost_center
        if ori == asgn:
            results.append(_v(4, "부서코드", "발생부서/귀속부서 일치", "OK",
                f"발생부서 = 귀속부서: {ori}"))
        else:
            results.append(_v(4, "부서코드", "발생부서/귀속부서 일치", "FAIL",
                f"발생부서({ori}) ≠ 귀속부서({asgn}) - 일치 필요",
                email_field="accounting.origin_cost_center"))

        acc = email.accounting.account_name
        if acc.startswith("판매촉진비") or acc.startswith("광고선전비"):
            prefix = "판매촉진비" if acc.startswith("판매촉진비") else "광고선전비"
            allowed = f"{prefix}-기타-기타"
            if acc == allowed:
                results.append(_v(4, "부서코드", "마케팅비 계정명 확인", "OK",
                    f"계정명 적절: {acc}"))
            else:
                results.append(_v(4, "부서코드", "마케팅비 계정명 확인", "FAIL",
                    f"계정명 '{acc}'은 '{allowed}'만 허용",
                    email_field="accounting.account_name"))
        return results

    # ─────────────────────────────────────────────────────────────────────
    # R5: 계정과목 (마케팅비 기타만 허용)
    # ─────────────────────────────────────────────────────────────────────
    def _check_account(self, email: EmailData) -> list[Violation]:
        acc = email.accounting.account_name
        marketing_prefixes = ["판매촉진비", "광고선전비"]
        for pfx in marketing_prefixes:
            if pfx in acc and "기타" not in acc:
                return [_v(5, "계정과목", "마케팅비 계정 확인", "FAIL",
                    f"신용카드 마케팅비는 '기타'만 허용 (현재: {acc})",
                    email_field="accounting.account_name")]
        return [_v(5, "계정과목", "마케팅비 계정 확인", "OK",
            f"계정과목 확인: {acc}")]

    # ─────────────────────────────────────────────────────────────────────
    # R6, R7: 원천세
    # ─────────────────────────────────────────────────────────────────────
    def _check_withholding_tax(self, email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]:
        results = []
        wt_code = email.accounting.withholding_tax_code

        # R6: 선물 + 10만원 초과
        if email.gift_info.is_gift:
            unit_price = email.gift_info.unit_price or 0
            if unit_price > GIFT_WITHHOLDING_MIN:
                if not wt_code:
                    results.append(_v(6, "원천세", "선물 원천세 코드 확인", "FAIL",
                        f"품목당 {unit_price:,}원 선물 - 원천세 코드 필수 (현재 없음)",
                        email_field="accounting.withholding_tax_code"))
                else:
                    # 직급별 코드 검증
                    for recipient in email.gift_info.recipients:
                        emp_id = recipient.get("employee_id", "")
                        name = recipient.get("name", "")
                        expected = None
                        if self.master:
                            expected = self.master.get_expected_withholding_code(employee_id=emp_id)
                        if expected and wt_code != expected:
                            results.append(_v(6, "원천세", "원천세 코드 직급 검증", "FAIL",
                                f"수령자 {name}({emp_id}): 직급 기준 코드={expected}, 이메일 코드={wt_code}",
                                email_field="accounting.withholding_tax_code"))
                        else:
                            results.append(_v(6, "원천세", "원천세 코드 직급 검증", "OK",
                                f"수령자 {name}: 원천세 코드 {wt_code} 확인"))
            elif unit_price > 0:
                if email.accounting.tax_code != "X1":
                    results.append(_v(6, "원천세", "10만원 이하 선물 세금코드", "WARN",
                        f"품목당 {unit_price:,}원 선물 - X1(매입세액 불공제) 코드 권장 (현재: {email.accounting.tax_code})",
                        email_field="accounting.tax_code"))
                else:
                    results.append(_v(6, "원천세", "10만원 이하 선물 세금코드", "OK",
                        f"품목당 {unit_price:,}원 선물 - X1 코드 확인"))

        # R7: 상품권 업종
        is_gift_voucher = ("상품권" in email.accounting.industry_code or
                           (receipt and receipt.is_gift_shop))
        if is_gift_voucher:
            if not wt_code:
                results.append(_v(7, "원천세", "상품권 원천세 코드 확인", "FAIL",
                    "상품권 결제 건: 원천세 코드 필수 (현재 없음)",
                    email_field="accounting.withholding_tax_code"))
            else:
                results.append(_v(7, "원천세", "상품권 원천세 코드 확인", "OK",
                    f"상품권 원천세 코드 확인: {wt_code}"))

        if not results:
            results.append(_v(6, "원천세", "원천세 해당 여부 확인", "OK",
                "원천세 해당 없음"))
        return results

    # ─────────────────────────────────────────────────────────────────────
    # R8: 이월처리
    # ─────────────────────────────────────────────────────────────────────
    def _check_carryover(self, email: EmailData) -> list[Violation]:
        posting_month = email.payment.posting_date[:7]   # "YYYY-MM"
        document_month = email.payment.document_date[:7]
        if posting_month == document_month:
            return [_v(8, "이월처리", "이월처리 여부 확인", "OK",
                f"당월 정산: {document_month}")]

        if email.accounting.tax_code == "VF":
            return [_v(8, "이월처리", "이월처리 여부 확인", "OK",
                f"이월처리이나 tax code 'VF' - 예외 적용")]

        has_doc = email.has_attachment_type("carryover_doc")
        if has_doc:
            return [_v(8, "이월처리", "이월처리 사유서 첨부", "OK",
                f"이월처리({document_month}→{posting_month}): 사유서 첨부 확인")]
        return [_v(8, "이월처리", "이월처리 사유서 첨부", "FAIL",
            f"이월처리({document_month}→{posting_month}): 임원 결재 이월처리 사유서 첨부 필요",
            email_field="attachments")]

    # ─────────────────────────────────────────────────────────────────────
    # R9~R12: 증빙첨부
    # ─────────────────────────────────────────────────────────────────────
    def _check_attachments(self, email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]:
        results = []
        acc = email.accounting.account_name
        total = email.payment.total_amount

        # R9: 여비교통비-기타 15,000원 이상 → 다인 식대 신청 양식
        if "여비교통비-기타" in acc and total >= MULTI_MEAL_MIN:
            has_form = email.has_attachment_type("multi_meal_form")
            if has_form:
                results.append(_v(9, "증빙첨부", "다인 식대 신청 양식 첨부", "OK",
                    f"여비교통비-기타 {total:,}원: 다인 식대 신청 양식 첨부 확인"))
            else:
                results.append(_v(9, "증빙첨부", "다인 식대 신청 양식 첨부", "FAIL",
                    f"여비교통비-기타 {total:,}원 (≥15,000원): 다인 식대 신청 양식 첨부 필요",
                    email_field="attachments"))

        # R10: 메가마트/판도라 → 영수증 필수
        is_megamart = ("메가마트" in email.payment.merchant_name or "판도라" in email.payment.merchant_name
                       or (receipt and receipt.is_megamart))
        if is_megamart:
            if email.has_receipt_image():
                results.append(_v(10, "증빙첨부", "메가마트/판도라 영수증 첨부", "OK",
                    "메가마트/판도라 영수증 첨부 확인"))
            else:
                results.append(_v(10, "증빙첨부", "메가마트/판도라 영수증 첨부", "FAIL",
                    "메가마트/판도라 결제: 승인번호 해당 영수증 첨부 필요",
                    email_field="attachments"))

        # R11: 오픈마켓 → 영수증 필수 (카드전표 불가)
        is_openmarket = receipt and receipt.is_openmarket
        if is_openmarket:
            receipt_atts = [a for a in email.attachments if a.type == "receipt_image"]
            card_slip_only = all("카드전표" in a.filename for a in receipt_atts)
            if not receipt_atts or card_slip_only:
                results.append(_v(11, "증빙첨부", "오픈마켓 영수증 첨부", "FAIL",
                    "오픈마켓 결제: 영수증 또는 세부내역 첨부 필요 (카드전표 불가) - 부가세 불공제 처리 예정",
                    email_field="attachments"))
            else:
                results.append(_v(11, "증빙첨부", "오픈마켓 영수증 첨부", "OK",
                    "오픈마켓 영수증 첨부 확인"))

        # R12: 품의 필요 계정
        for req_acc in OPINION_REQUIRED_ACCOUNTS:
            if req_acc in acc:
                if email.has_attachment_type("opinion_doc"):
                    results.append(_v(12, "증빙첨부", "품의서 첨부 확인", "OK",
                        f"{acc}: 품의서 첨부 확인"))
                else:
                    results.append(_v(12, "증빙첨부", "품의서 첨부 확인", "WARN",
                        f"{acc}: 품의서(GWP 품의 등) 첨부 필요",
                        email_field="attachments"))
                break

        if not results:
            results.append(_v(9, "증빙첨부", "증빙첨부 확인", "OK", "증빙첨부 이상 없음"))
        return results

    # ─────────────────────────────────────────────────────────────────────
    # R13: 택시비
    # ─────────────────────────────────────────────────────────────────────
    def _check_taxi(self, email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]:
        is_taxi = (receipt and receipt.is_taxi) or "택시" in email.payment.merchant_name
        if not is_taxi:
            return [_v(13, "택시비", "택시비 해당 여부", "OK", "택시비 해당 없음")]

        total = email.payment.total_amount
        results = []

        # 금액 초과 확인
        if total > TAXI_MAX_AMOUNT:
            results.append(_v(13, "택시비", "택시비 한도 확인", "FAIL",
                f"택시비 {total:,}원 - 편도 {TAXI_MAX_AMOUNT:,}원 초과",
                email_field="payment.total_amount"))
        else:
            results.append(_v(13, "택시비", "택시비 한도 확인", "OK",
                f"택시비 {total:,}원 - 편도 한도 이내"))

        # 시각 확인
        t_time = receipt.transaction_time if receipt else None
        memo = email.memo
        if t_time:
            hour = int(t_time.split(":")[0])
            if hour < 24:  # 자정 이전
                is_business = bool(re.search(
                    r'업무|출장|고객|미팅|회의|귀가|야근|출근|업무용', memo, re.IGNORECASE
                ))
                if is_business:
                    results.append(_v(13, "택시비", "심야 택시 사용 목적", "OK",
                        f"자정 이전({t_time}) 업무 목적 확인: {memo[:30]}"))
                else:
                    results.append(_v(13, "택시비", "심야 택시 사용 목적", "WARN",
                        f"자정 이전({t_time}) 사용 - 적요에 업무 목적 기재 필요 (현재: {memo[:30]})",
                        email_field="memo"))
        return results

    # ─────────────────────────────────────────────────────────────────────
    # R14: 휴일 사용
    # ─────────────────────────────────────────────────────────────────────
    def _check_holiday(self, email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]:
        is_holiday = receipt.is_holiday if receipt else False
        if not is_holiday:
            return [_v(14, "휴일사용", "휴일 사용 여부", "OK", "평일 결제 확인")]
        memo = email.memo
        is_business = bool(re.search(
            r'업무|출장|고객|미팅|회의|행사|교육|세미나', memo, re.IGNORECASE
        ))
        if is_business:
            return [_v(14, "휴일사용", "휴일 사용 목적 확인", "OK",
                f"휴일 결제 - 업무 목적 확인: {memo[:30]}")]
        return [_v(14, "휴일사용", "휴일 사용 목적 확인", "WARN",
            f"휴일 결제 - 적요에 업무 관련 내용 필요 (현재: {memo[:30]})",
            email_field="memo")]

    # ─────────────────────────────────────────────────────────────────────
    # R15: 결재권자 부서 확인
    # ─────────────────────────────────────────────────────────────────────
    def _check_approver(self, email: EmailData) -> list[Violation]:
        submitter_dept = email.submitter.department_code
        approver_dept = email.approver.department_code
        # 동일 부서이거나 approver 부서가 submitter 부서 코드를 포함(상위조직)
        if submitter_dept == approver_dept or submitter_dept.startswith(approver_dept):
            return [_v(15, "결재권자", "결재권자 소속 확인", "OK",
                f"결재권자({email.approver.name}) 부서 확인: {approver_dept}")]
        return [_v(15, "결재권자", "결재권자 소속 확인", "WARN",
            f"결재권자({email.approver.name}) 부서({approver_dept})가 발생부서({submitter_dept})와 불일치 - 상위조직 여부 확인 필요",
            email_field="approver.department_code")]
