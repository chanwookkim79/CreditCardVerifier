"""
신용카드 영수증 점검 시스템 메인
사용법:
  python main.py --email test_data/emails/email_normal_01.json --receipt test_data/receipts/receipt_mock_01.json
  python main.py --all-emails --mock-receipts
  python main.py --email test_data/emails/email_vat_violation.json --receipt test_data/receipts/receipt_mock_02.json --json
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
from glob import glob

# Windows 콘솔 UTF-8
if sys.stdout.encoding != "utf-8":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
if sys.stderr.encoding != "utf-8":
    sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", buffering=1)

from core.logger import get_logger
log = get_logger("checker")

from config import (
    AGENCY_CSV, WITHHOLDING_CSV,
    BASE_DIR, TEST_DATA_DIR, EMAIL_SUBJECT_FILTER,
)
from master.master_data_loader import MasterDataLoader
from core.email_parser import EmailParser
from core.receipt_parser import ReceiptParser
from core.cross_validator import CrossValidator
from models.check_result import CheckResult, CheckStatus
from core.results_writer import write_result, write_txt_report, is_already_processed

STATUS_ICON = {
    "OK": "✅", "WARN": "⚠️ ", "FAIL": "❌", "INFO": "ℹ️ ", "SKIP": "⏭️ ",
}
STATUS_COLOR = {
    "OK": "\033[92m", "WARN": "\033[93m", "FAIL": "\033[91m",
    "INFO": "\033[96m", "SKIP": "\033[90m",
}
RESET = "\033[0m"


def print_result(result: CheckResult, use_color: bool = True) -> None:
    sep = "─" * 65
    print(f"\n{sep}")
    print(f"📧 이메일: {result.email_id}  |  기안자: {result.submitter_name} ({result.submitter_email})")
    print(sep)
    for v in sorted(result.violations,
                    key=lambda x: (x.status == CheckStatus.OK, x.status == CheckStatus.SKIP, x.rule_no)):
        icon = STATUS_ICON.get(v.status.value, "  ")
        color = STATUS_COLOR.get(v.status.value, "") if use_color else ""
        reset = RESET if use_color else ""
        print(f"  {color}{icon} [R{v.rule_no:02d}] [{v.category}] {v.check_name}{reset}")
        print(f"       {v.message}")
    s = result.summary()
    print(f"\n  요약: ✅ {s['OK']}건 정상  ⚠️  {s['WARN']}건 주의  ❌ {s['FAIL']}건 실패")
    print(sep)


def process_single(email_path: str, receipt_path: str,
                   master: MasterDataLoader,
                   use_ocr: bool = False,
                   output_json: bool = False,
                   receipt_index: int | None = None,
                   ocr_items: list[dict] | None = None,
                   receipt_count: int = 1) -> CheckResult:

    t0 = time.perf_counter()
    email_name = Path(email_path).name
    receipt_name = Path(receipt_path).name if receipt_path else "없음"

    log.info("=" * 60)
    log.info(f"[START] 처리 시작")
    log.info(f"        이메일 파일  : {email_name}")
    log.info(f"        영수증 파일  : {receipt_name}")

    # ── 1. 이메일 파싱 ────────────────────────────────────────────────
    log.debug(f"[PARSE] 이메일 JSON 파싱 시작: {email_path}")
    parser = EmailParser()
    email = parser.parse_json_file(email_path)
    log.info(f"[PARSE] 이메일 파싱 완료")

    # ── 제목 필터 ────────────────────────────────────────────────────
    if EMAIL_SUBJECT_FILTER not in email.subject:
        log.info(f"[SKIP] 처리 대상 아님 (제목 필터 불일치): {email.subject}")
        return None

    # ── 중복 체크 ────────────────────────────────────────────────────
    if is_already_processed(email.samsung_doc_no):
        log.warning(f"[SKIP] 이미 처리된 전표번호: {email.samsung_doc_no} — 중복 실행 건너뜀")
        print(f"⏭️  [SKIP] 전표번호 {email.samsung_doc_no} 는 이미 처리된 건입니다. 건너뜁니다.")
        return None
    log.info(f"        이메일 ID    : {email.email_id}")
    log.info(f"        삼성전표번호 : {email.samsung_doc_no or '(없음)'}")
    log.info(f"        기안자       : {email.submitter.name} ({email.submitter.email})")
    log.info(f"        부서         : {email.submitter.department} [{email.submitter.department_code}]")
    log.info(f"        결재권자     : {email.approver.name} [{email.approver.department_code}]")
    log.info(f"        업체명       : {email.payment.merchant_name}")
    log.info(f"        승인번호     : {email.payment.approval_no}")
    log.info(f"        결제금액     : {email.payment.total_amount:,}원  (부가세 {email.payment.vat_amount:,}원)")
    log.info(f"        사업자번호   : {email.payment.biz_no}")
    log.info(f"        계정과목     : {email.accounting.account_name}")
    log.info(f"        발생/귀속부서: {email.accounting.origin_cost_center} / {email.accounting.assigned_cost_center}")
    log.info(f"        불공제 사유  : {email.accounting.nontax_reason}")
    log.info(f"        원천세 코드  : {email.accounting.withholding_tax_code or '없음'}")
    log.info(f"        선물 여부    : {'예' if email.gift_info.is_gift else '아니오'}")
    log.info(f"        적요         : {email.memo}")
    log.info(f"        첨부파일     : {[a.filename + '(' + a.type + ')' for a in email.attachments]}")
    log.debug(f"        Posting date : {email.payment.posting_date}")
    log.debug(f"        Document date: {email.payment.document_date}")
    log.debug(f"        Tax code     : {email.accounting.tax_code}")

    # ── 2. 영수증 처리 ────────────────────────────────────────────────
    rec_parser = ReceiptParser(master)
    receipt = None

    if receipt_path and Path(receipt_path).exists():
        if receipt_path.endswith(".json"):
            log.info(f"[RECEIPT] Mock JSON 영수증 로드: {receipt_name}")
            receipt = rec_parser.from_json_file(receipt_path)
        elif use_ocr:
            # 다중 영수증: multi_receipt_ocr에서 이미 분할·OCR된 items를 받음
            # (ocr_items가 직접 전달된 경우)
            if ocr_items is not None:
                log.info(f"[OCR] 사전 분할된 items {len(ocr_items)}개 사용")
                receipt = rec_parser.parse(ocr_items, source_file=receipt_path)
            else:
                log.info(f"[OCR] 단일 영수증 OCR 처리: {receipt_name}")
                from core.ocr_engine import OCREngine
                ocr = OCREngine()
                t_ocr = time.perf_counter()
                items = ocr.run(receipt_path)
                log.info(f"[OCR] OCR 완료: {len(items)}개 텍스트 추출 ({time.perf_counter()-t_ocr:.1f}초)")
                log.debug(f"[OCR] 추출 텍스트 목록: {[i['text'] for i in items]}")
                receipt = rec_parser.parse(items, source_file=receipt_path)
        else:
            log.warning(f"[RECEIPT] OCR 미사용 모드 - 이미지 파일 건너뜀 (--use-ocr 추가 시 OCR 실행): {receipt_name}")
    else:
        log.warning(f"[RECEIPT] 영수증 파일 없음: {receipt_path or '경로 미지정'}")

    if receipt:
        log.info(f"[RECEIPT] 영수증 파싱 완료")
        log.info(f"          가맹점명     : {receipt.merchant or '(미확인)'}")
        log.info(f"          사업자번호   : {receipt.biz_no or '(미확인)'}")
        if len(receipt.all_biz_nos) > 1:
            log.info(f"          전체 사업자  : {receipt.all_biz_nos} (대행사 필터 후: {receipt.biz_no})")
        log.info(f"          승인번호     : {receipt.approval_no or '(미확인)'}")
        log.info(f"          거래일시     : {receipt.date or '(미확인)'} {receipt.transaction_time or ''}")
        vat_str = f"{receipt.vat:,}원" if receipt.vat is not None else "(미확인)"
        log.info(f"          합계/부가세  : {receipt.total:,}원 / {vat_str}" if receipt.total else "          금액: (미확인)")
        log.info(f"          불공제 키워드: {receipt.nontax_keywords or '없음'}")
        log.info(f"          업체 유형    : "
                 f"메가마트={receipt.is_megamart} | "
                 f"오픈마켓={receipt.is_openmarket} | "
                 f"상품권={receipt.is_gift_shop} | "
                 f"택시={receipt.is_taxi} | "
                 f"휴일={receipt.is_holiday}")
    else:
        log.warning("[RECEIPT] 영수증 데이터 없음 - 일부 규칙 WARN 처리됩니다")

    # ── 3. 교차 검증 ─────────────────────────────────────────────────
    log.info(f"[CHECK] 점검규칙 적용 시작 ({'이메일+영수증 교차검증' if receipt else '이메일 단독 점검'})"
             + (f" (전표 내 영수증 {receipt_count}건 — R01 금액비교 SKIP)" if receipt_count > 1 else ""))
    validator = CrossValidator(master)
    violations = validator.validate(email, receipt, receipt_count=receipt_count)

    # 규칙별 상세 로그
    for v in sorted(violations, key=lambda x: x.rule_no):
        level = {
            "FAIL": log.error,
            "WARN": log.warning,
            "OK":   log.debug,
            "INFO": log.debug,
            "SKIP": log.debug,
        }.get(v.status.value, log.debug)
        level(f"[R{v.rule_no:02d}] {v.status.value:4s} [{v.category}] {v.check_name} → {v.message}")

    # ── 4. 결과 집계 ─────────────────────────────────────────────────
    result = CheckResult(
        email_id=email.email_id,
        subject=email.subject,
        submitter_email=email.submitter.email,
        submitter_name=email.submitter.name,
        violations=violations,
    )
    s = result.summary()
    elapsed = time.perf_counter() - t0

    log.info(f"[RESULT] 점검 완료: ✅ OK {s['OK']}건  ⚠️  WARN {s['WARN']}건  ❌ FAIL {s['FAIL']}건  (소요 {elapsed:.2f}초)")

    # ── 5. 출력 / 통보 ────────────────────────────────────────────────
    if output_json:
        print(json.dumps({
            "email_id": result.email_id,
            "submitter": result.submitter_email,
            "elapsed_sec": round(elapsed, 2),
            "summary": result.summary(),
            "violations": [
                {
                    "rule_no": v.rule_no,
                    "category": v.category,
                    "check_name": v.check_name,
                    "status": v.status.value,
                    "message": v.message,
                    "email_field": v.email_field,
                    "receipt_field": v.receipt_field,
                }
                for v in result.violations
            ],
        }, ensure_ascii=False, indent=2))
    else:
        print_result(result)

        # ── TXT 리포트 저장 ───────────────────────────────────────────
        txt_path = write_txt_report(email, receipt, result, receipt_index)
        log.info(f"[REPORT] TXT 리포트 저장: {txt_path.name}")

        # ── results CSV 기록 ──────────────────────────────────────────
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        write_result(ts, email, receipt, result, txt_saved=True)
        log.info(f"[RESULT] checker results.csv 기록 완료")

    log.info(f"[END]   처리 완료: {email.email_id}")
    log.info("=" * 60)
    return result


def process_email(email_path: str, receipt_paths: list[str],
                  master: MasterDataLoader,
                  use_ocr: bool = False,
                  output_json: bool = False) -> list[CheckResult]:
    """이메일 1건 + 영수증 N건 처리.

    이미지 파일(--use-ocr)인 경우 MultiReceiptOCR로 자동 분할해
    영수증 1장씩 process_single에 전달.
    영수증이 2건 이상이면 TXT 파일명에 _01, _02 ... 접미사를 붙인다.
    """
    results = []

    for rpath in receipt_paths:
        is_image = rpath and not rpath.endswith(".json") and Path(rpath).exists()

        if use_ocr and is_image:
            # ── 다중 영수증 자동 분할 OCR ──
            log.info(f"[MULTI-OCR] 다중 영수증 분할 시작: {Path(rpath).name}")
            from core.ocr_engine import OCREngine
            from core.multi_receipt_ocr import MultiReceiptOCR
            ocr_engine = OCREngine()
            multi_ocr  = MultiReceiptOCR(ocr_engine)

            t_split = time.perf_counter()
            all_items = multi_ocr.run(rpath)   # list[list[dict]]
            log.info(
                f"[MULTI-OCR] 분할 완료: {len(all_items)}장 "
                f"({time.perf_counter()-t_split:.1f}초)"
            )

            total_count = len(all_items)
            use_index = total_count > 1
            for i, items in enumerate(all_items, start=1):
                idx = i if use_index else None
                log.info(f"[MULTI-OCR] 영수증 [{i}/{total_count}] 처리 중 ({len(items)}개 텍스트)")
                res = process_single(
                    email_path, rpath, master,
                    use_ocr=True,
                    output_json=output_json,
                    receipt_index=idx,
                    ocr_items=items,
                    receipt_count=total_count,
                )
                if res is not None:
                    results.append(res)
        else:
            # ── 단일 처리 (JSON mock 또는 단일 이미지) ──
            res = process_single(
                email_path, rpath, master,
                use_ocr=use_ocr,
                output_json=output_json,
                receipt_index=None,
                ocr_items=None,
            )
            if res is not None:
                results.append(res)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="신용카드 영수증 점검 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 단일 이메일 + mock 영수증 JSON
  python main.py --email test_data/emails/email_normal_01.json --receipt test_data/receipts/receipt_mock_01.json

  # 단일 이메일 + 실제 영수증 이미지 OCR
  python main.py --email test_data/emails/email_normal_01.json --receipt 영수증1.jpg --use-ocr

  # 테스트 데이터 전체 일괄 실행
  python main.py --all-emails --mock-receipts

  # JSON 출력
  python main.py --email test_data/emails/email_vat_violation.json --receipt test_data/receipts/receipt_mock_02.json --json

        """
    )
    parser.add_argument("--email", help="이메일 JSON 파일 경로")
    parser.add_argument("--receipt", nargs="+", metavar="PATH",
                        help="영수증 파일 경로 (.json=mock, .jpg/.png=OCR). 복수 지정 가능")
    parser.add_argument("--use-ocr", action="store_true", help="이미지 파일 OCR 처리 활성화")
    parser.add_argument("--all-emails", action="store_true", help="test_data/emails/ 전체 처리")
    parser.add_argument("--mock-receipts", action="store_true", help="test_data/receipts/ mock JSON 자동 매칭")
    parser.add_argument("--json", action="store_true", help="JSON 형식 출력")
    args = parser.parse_args()

    from core.logger import CSV_LOG_FILE
    log.info(f"신용카드 영수증 점검 시스템 시작 | 로그파일: {CSV_LOG_FILE}")
    log.debug(f"마스터 데이터 로드: {AGENCY_CSV.name}, {WITHHOLDING_CSV.name}")
    master = MasterDataLoader(AGENCY_CSV, WITHHOLDING_CSV)
    log.info(f"마스터 데이터 로드 완료")

    if args.all_emails:
        email_files = sorted(glob(str(TEST_DATA_DIR / "emails" / "*.json")))
        receipt_files = sorted(glob(str(TEST_DATA_DIR / "receipts" / "receipt_mock_*.json")))
        pairs = list(zip(email_files, receipt_files))
        if not pairs:
            log.error("테스트 이메일 파일이 없습니다.")
            sys.exit(1)
        log.info(f"일괄 처리: 총 {len(pairs)}건")
        all_results = []
        for e_path, r_path in pairs:
            for res in process_email(e_path, [r_path], master,
                                     use_ocr=args.use_ocr,
                                     output_json=args.json):
                all_results.append(res)

        total_fail = sum(r.summary()["FAIL"] for r in all_results)
        total_warn = sum(r.summary()["WARN"] for r in all_results)
        total_ok   = sum(r.summary()["OK"]   for r in all_results)
        print(f"\n{'='*65}")
        print(f"전체 {len(all_results)}건 처리 완료")
        print(f"총 점검: ✅ {total_ok}건 정상  ⚠️  {total_warn}건 주의  ❌ {total_fail}건 실패")
        print(f"{'='*65}")
        log.info(f"[BATCH] 일괄 처리 완료: {len(all_results)}건 | "
                 f"OK={total_ok} WARN={total_warn} FAIL={total_fail}")

    elif args.email:
        receipt_paths = args.receipt or [""]
        process_email(args.email, receipt_paths, master,
                      use_ocr=args.use_ocr,
                      output_json=args.json)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
