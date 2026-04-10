"""
신용카드 영수증 점검 CLI 도구
사용법:
  python receipt_checker.py 영수증1.jpg
  python receipt_checker.py *.jpg
  python receipt_checker.py --all
  python receipt_checker.py --all --json
"""

import os, sys, re, json, argparse, warnings, glob
from pathlib import Path

# Windows 콘솔 UTF-8 출력 설정
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
if sys.stderr.encoding != 'utf-8':
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)

# ── PaddleOCR oneDNN 버그 우회 (Windows CPU) ──────────────────────────
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
warnings.filterwarnings('ignore')

import paddlex.inference.utils.pp_option as _pp_opt
_orig = _pp_opt.get_default_run_mode
def _patched(model_name, device_type):
    return 'paddle' if device_type == 'cpu' else _orig(model_name, device_type)
_pp_opt.get_default_run_mode = _patched
# ─────────────────────────────────────────────────────────────────────

from paddleocr import PaddleOCR

RULES_FILE = Path(__file__).parent / 'inspection_rules.json'

# ── OCR 초기화 ──────────────────────────────────────────────────────────
_ocr = None

def get_ocr():
    global _ocr
    if _ocr is None:
        print("OCR 모델 로딩 중...", flush=True)
        _ocr = PaddleOCR(
            use_doc_orientation_classify=True,   # 회전된 영수증 자동 보정
            use_doc_unwarping=False,
            use_textline_orientation=True,
            lang='korean',
            text_detection_model_name='PP-OCRv5_mobile_det',
            text_recognition_model_name='korean_PP-OCRv5_mobile_rec',
        )
        print("모델 로딩 완료.", flush=True)
    return _ocr


# ── OCR 실행 ────────────────────────────────────────────────────────────
def run_ocr(image_path: str) -> list[dict]:
    """OCR 실행 후 [{text, x, y, conf}] 리스트 반환 (y순 정렬)"""
    ocr = get_ocr()
    result = ocr.ocr(image_path)
    if not result or not result[0]:
        return []

    r = result[0]
    items = []
    for text, score, poly in zip(r['rec_texts'], r['rec_scores'], r['rec_polys']):
        items.append({
            'text': text,
            'x': float(poly[0][0]),
            'y': float(poly[0][1]),
            'conf': round(float(score), 3),
        })
    items.sort(key=lambda i: (i['y'], i['x']))
    return items


# ── 영수증 필드 파싱 ────────────────────────────────────────────────────
def parse_receipt(items: list[dict]) -> dict:
    """OCR 텍스트 목록에서 영수증 주요 필드 추출"""
    texts = [i['text'] for i in items]
    full = '\n'.join(texts)

    def find(patterns, text=full):
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m.group(1).strip() if m.lastindex else m.group(0).strip()
        return None

    def find_amount(keyword_patterns):
        """키워드 근처 숫자 찾기"""
        for i, item in enumerate(items):
            for p in keyword_patterns:
                if re.search(p, item['text'], re.IGNORECASE):
                    # 같은 줄이나 다음 줄에서 금액 찾기
                    search_range = items[i:i+3]
                    for s in search_range:
                        m = re.search(r'([\d,]+)\s*원?', s['text'])
                        if m:
                            return m.group(1).replace(',', '')
        return None

    # 가맹점명: 상단 첫 번째 의미있는 텍스트
    merchant = None
    for item in items[:10]:
        t = item['text'].strip()
        if len(t) >= 2 and not re.match(r'^[\d\-\s\(\)]+$', t):
            if not re.search(r'사업자|대표|전화|TEL|tel', t, re.I):
                merchant = t
                break

    # 사업자번호
    biz_no = find([
        r'(\d{3}-\d{2}-\d{5})',
        r'사업자[번호\s]*[:：]?\s*(\d{3}[-\s]?\d{2}[-\s]?\d{5})',
    ])

    # 승인번호
    approval_no = find([
        r'승인[번호\s]*[:：]?\s*(\d{6,10})',
        r'승인\s+(\d{6,10})',
        r'[Aa]pproval\s*[Nn]o\.?\s*[:：]?\s*(\d{6,10})',
    ])

    # 거래일시
    date = find([
        r'(\d{4}[./\-]\d{2}[./\-]\d{2}[\s\-]+\d{2}:\d{2}(?::\d{2})?)',
        r'(\d{4}[./\-]\d{2}[./\-]\d{2})',
        r'거래일시\s*[:：]?\s*(\d{4}\d{2}\d{2}\s*\d{2}:\d{2})',
    ])

    # 합계금액
    total = find([
        r'합\s*계\s*[:：]?\s*([\d,]+)\s*원',
        r'총\s*금\s*액\s*[:：]?\s*([\d,]+)\s*원',
        r'결제금액\s*[:：]?\s*([\d,]+)\s*원',
        r'청구금액\s*[:：]?\s*([\d,]+)\s*원',
    ])
    if total:
        total = total.replace(',', '')

    # 부가세
    vat = find([
        r'부가세\s*[:：]?\s*([\d,]+)\s*원?',
        r'세\s*액\s*[:：]?\s*([\d,]+)\s*원?',
        r'VAT\s*[:：]?\s*([\d,]+)\s*원?',
    ])
    if vat:
        vat = vat.replace(',', '')

    # 공급가액
    supply = find([
        r'공급가액\s*[:：]?\s*([\d,]+)\s*원?',
        r'공급\s*금\s*액\s*[:：]?\s*([\d,]+)\s*원?',
    ])
    if supply:
        supply = supply.replace(',', '')

    # 카드번호 (마스킹)
    card_no = find([
        r'(\d{4}[-\s*]+\d{4}[-\s*]+[\d*]{4}[-\s*]+[\d*]{4})',
        r'카드번호\s*[:：]?\s*([\d\-\*\s]{13,19})',
    ])

    # 품목 키워드 탐지 (불공제 항목)
    nontax_keywords = ['골프', '스크린골프', '수영장', '볼링', '당구', '상품권', '화환', '과일',
                       '정육', '항공', '철도', '택시', '주차', '입장권', '영화', '공연', '박물관',
                       '도서', '교재', '선물', 'AI', 'chatgpt', 'ChatGPT', 'Gemini', 'Claude',
                       '챗지피티', '구독']
    found_nontax = [kw for kw in nontax_keywords if re.search(kw, full, re.IGNORECASE)]

    # 업체 유형 탐지
    is_megamart = bool(re.search(r'메가마트|판도라', full, re.IGNORECASE))
    is_openmarket = bool(re.search(r'쿠팡|11번가|G마켓|옥션|위메프|티몬|인터파크|네이버쇼핑|카카오쇼핑', full, re.IGNORECASE))

    return {
        'merchant': merchant,
        'biz_no': biz_no,
        'approval_no': approval_no,
        'date': date,
        'total': total,
        'vat': vat,
        'supply': supply,
        'card_no': card_no,
        'nontax_keywords': found_nontax,
        'is_megamart': is_megamart,
        'is_openmarket': is_openmarket,
        'raw_text': full,
    }


# ── 점검 규칙 적용 ──────────────────────────────────────────────────────
def check_rules(fields: dict) -> list[dict]:
    """추출된 필드에 점검 규칙 적용, 결과 리스트 반환"""
    results = []

    def add(no, category, check, status, message=''):
        results.append({
            'no': no,
            'category': category,
            'check': check,
            'status': status,  # 'OK' | 'WARN' | 'FAIL' | 'INFO'
            'message': message,
        })

    # Rule 1: 부가세 금액 존재 여부
    if fields['vat']:
        add(1, '부가세', '부가세 금액 확인', 'OK', f"세액: {int(fields['vat']):,}원")
    else:
        add(1, '부가세', '부가세 금액 확인', 'WARN', '영수증에서 부가세 금액을 찾지 못함 (수동 확인 필요)')

    # Rule 2: 사업자번호 존재 여부
    if fields['biz_no']:
        add(2, '실거래사업자번호', '사업자번호 확인', 'OK', f"사업자번호: {fields['biz_no']}")
    else:
        add(2, '실거래사업자번호', '사업자번호 확인', 'FAIL', '영수증에서 사업자번호를 찾지 못함')

    # Rule 3: 불공제 항목 탐지
    if fields['nontax_keywords']:
        add(3, '부가세불공제', '불공제 항목 탐지', 'WARN',
            f"불공제 가능 키워드 발견: {', '.join(fields['nontax_keywords'])} → 불공제 사유 확인 필요")
    else:
        add(3, '부가세불공제', '불공제 항목 탐지', 'OK', '불공제 항목 키워드 없음')

    # Rule 10: 메가마트/판도라 → 영수증 필수
    if fields['is_megamart']:
        add(10, '증빙첨부', '메가마트/판도라 영수증 첨부', 'WARN',
            '메가마트/판도라 결제 → 승인번호 해당 영수증 필수 첨부 확인')

    # Rule 11: 오픈마켓 → 영수증 필수
    if fields['is_openmarket']:
        add(11, '증빙첨부', '유통업체/오픈마켓 영수증 첨부', 'WARN',
            '유통업체/오픈마켓 결제 → 영수증 또는 세부내역 필수 첨부 (카드전표 불가)')

    # AI 구독 탐지 (Rule 3 세부)
    ai_keywords = ['chatgpt', 'gemini', 'claude', 'openai', '챗지피티', 'AI 구독']
    found_ai = [kw for kw in ai_keywords if re.search(kw, fields['raw_text'], re.IGNORECASE)]
    if found_ai:
        add(3, 'AI구독', 'AI 서비스 구독 탐지', 'WARN',
            f"AI 서비스 구독 키워드 발견: {', '.join(found_ai)} → 계정='지급수수료-기타', 불공제사유='기타' 필수")

    # 승인번호 존재 여부 (기본 정보)
    if fields['approval_no']:
        add(0, '기본정보', '승인번호 확인', 'INFO', f"승인번호: {fields['approval_no']}")
    else:
        add(0, '기본정보', '승인번호 확인', 'WARN', '승인번호를 찾지 못함')

    return results


# ── 출력 포맷 ───────────────────────────────────────────────────────────
STATUS_ICON = {'OK': '✅', 'WARN': '⚠️ ', 'FAIL': '❌', 'INFO': 'ℹ️ '}
STATUS_COLOR = {'OK': '\033[92m', 'WARN': '\033[93m', 'FAIL': '\033[91m', 'INFO': '\033[96m'}
RESET = '\033[0m'

def print_result(image_path: str, fields: dict, checks: list[dict], use_color=True):
    name = Path(image_path).name
    sep = '─' * 60

    print(f"\n{sep}")
    print(f"📄 {name}")
    print(sep)

    # 기본 정보
    print(f"  가맹점명  : {fields['merchant'] or '(미확인)'}")
    print(f"  사업자번호: {fields['biz_no'] or '(미확인)'}")
    print(f"  거래일시  : {fields['date'] or '(미확인)'}")
    print(f"  승인번호  : {fields['approval_no'] or '(미확인)'}")
    if fields['total']:
        print(f"  합계금액  : {int(fields['total']):,}원")
    if fields['vat']:
        print(f"  부가세    : {int(fields['vat']):,}원")
    if fields['supply']:
        print(f"  공급가액  : {int(fields['supply']):,}원")

    print(f"\n  {'점검 결과':─<50}")
    for c in sorted(checks, key=lambda x: (x['status'] == 'INFO', x['no'])):
        icon = STATUS_ICON.get(c['status'], '  ')
        color = STATUS_COLOR.get(c['status'], '') if use_color else ''
        reset = RESET if use_color else ''
        label = f"[{c['no']:02d}] {c['category']}" if c['no'] > 0 else f"     {c['category']}"
        msg = f" → {c['message']}" if c['message'] else ''
        print(f"  {color}{icon} {label}: {c['check']}{msg}{reset}")

    # 요약
    counts = {'OK': 0, 'WARN': 0, 'FAIL': 0}
    for c in checks:
        if c['status'] in counts:
            counts[c['status']] += 1
    print(f"\n  요약: ✅ {counts['OK']}건 정상  ⚠️  {counts['WARN']}건 주의  ❌ {counts['FAIL']}건 실패")
    print(sep)


# ── 메인 ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='신용카드 영수증 점검 도구',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python receipt_checker.py 영수증1.jpg
  python receipt_checker.py 영수증1.jpg 영수증3.jpg
  python receipt_checker.py --all
  python receipt_checker.py --all --json > result.json
        """
    )
    parser.add_argument('images', nargs='*', help='분석할 영수증 이미지 경로')
    parser.add_argument('--all', action='store_true', help='현재 폴더의 모든 jpg/png 분석')
    parser.add_argument('--json', action='store_true', help='JSON 형식으로 출력')
    parser.add_argument('--no-color', action='store_true', help='색상 출력 비활성화')
    args = parser.parse_args()

    # 대상 파일 수집
    targets = list(args.images)
    if args.all:
        targets = sorted(
            glob.glob('*.jpg') + glob.glob('*.jpeg') + glob.glob('*.png')
        )
        # 점검규칙 이미지 제외
        targets = [t for t in targets if '점검규칙' not in t and 'rules' not in t]

    if not targets:
        parser.print_help()
        sys.exit(1)

    all_results = []

    for img_path in targets:
        if not os.path.exists(img_path):
            print(f"❌ 파일 없음: {img_path}", file=sys.stderr)
            continue

        print(f"\n처리 중: {img_path} ...", file=sys.stderr)
        ocr_items = run_ocr(img_path)

        if not ocr_items:
            print(f"⚠️  OCR 결과 없음: {img_path}", file=sys.stderr)
            continue

        fields = parse_receipt(ocr_items)
        checks = check_rules(fields)

        if args.json:
            all_results.append({
                'file': img_path,
                'fields': {k: v for k, v in fields.items() if k != 'raw_text'},
                'checks': checks,
            })
        else:
            print_result(img_path, fields, checks, use_color=not args.no_color)

    if args.json:
        print(json.dumps(all_results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
