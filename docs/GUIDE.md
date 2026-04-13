# 신용카드 영수증 점검 시스템 — 운영·개발 가이드

> 최종 업데이트: 2026-04-13 (attachment_extractor, 중복점검, POP3 수신 반영)
> 대상 독자: 시스템 운영자 / 유지보수 개발자

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [환경 구축](#2-환경-구축)
3. [시스템 아키텍처](#3-시스템-아키텍처)
4. [입출력 데이터 명세](#4-입출력-데이터-명세)
5. [점검 규칙 (R01 ~ R15)](#5-점검-규칙-r01--r15)
6. [실행 방법](#6-실행-방법)
7. [설정값 참조 (config.py)](#7-설정값-참조-configpy)
8. [코드 명세서](#8-코드-명세서)
9. [파일 명세서](#9-파일-명세서)
10. [유지보수 가이드](#10-유지보수-가이드)

---

## 1. 프로젝트 개요

### 목적

SAP/NERP에서 내려오는 **신용카드 결제 승인 이메일**을 자동으로 분석하여, 첨부된 영수증 이미지와 교차 검증 후 15개 비즈니스 규칙(R01~R15)을 적용한다. 점검 결과는 TXT 파일로 저장하고, 처리 이력은 CSV로 누적 기록한다.

### 처리 대상 필터

이메일 제목에 아래 문자열이 포함된 건만 처리한다.

```
[myF] 신용카드 경비
```

### 주요 기능 요약

| 기능 | 설명 |
|------|------|
| 메일 자동 수신 | POP3로 `[myF] 신용카드 경비` 메일 자동 수신 |
| 이메일 파싱 | SAP 이메일 JSON → 구조화된 데이터 |
| 첨부파일 추출 | PDF/PPTX/XLSX/DOCX/DOC/PPT/XLS 에서 영수증 이미지 자동 추출 |
| OCR | 영수증 이미지 텍스트 추출 (PaddleOCR, 한글 특화) |
| 교차 검증 | 이메일 본문 ↔ 영수증 15개 규칙 자동 검증 |
| 중복 방지 | 삼성전표번호(samsung_doc_no) 기준 기처리 건 자동 스킵 |
| 점검 리포트 | TXT 파일 저장 (`logs/reports/년월일_기안자ID_삼성전표번호.txt`, 복수 영수증 시 `_01.txt`, `_02.txt` …) |
| 로그 기록 | 상세 로그 CSV + 이메일 단위 결과 CSV |

---

## 2. 환경 구축

### 2.1 사전 요구사항

| 항목 | 버전 | 비고 |
|------|------|------|
| Python | 3.13 | 3.10 이상 권장 (`str \| Path` 문법 사용) |
| OS | Windows 11 | Linux/macOS 가능하나 OCR 경로 확인 필요 |
| pip | 최신 | `python -m pip install --upgrade pip` |

### 2.2 OCR 도구 비교

영수증 이미지 분석에 적합한 도구를 비교한 후 **PaddleOCR**를 선택하였다.

| 항목 | **PaddleOCR** ✅ | Tesseract | EasyOCR | Google Vision API | Naver Clova OCR |
|------|:-:|:-:|:-:|:-:|:-:|
| 한글 정확도 | ★★★★★ | ★★★ | ★★★★ | ★★★★★ | ★★★★★ |
| 영수증 특화 | ★★★★ | ★★ | ★★★ | ★★★★ | ★★★★★ |
| 오프라인 동작 | ✅ | ✅ | ✅ | ❌ | ❌ |
| 비용 | 무료 | 무료 | 무료 | 유료(무료 한도) | 유료 |
| Windows 지원 | ✅ (주의사항 있음) | ✅ | ✅ | ✅ | ✅ |
| Python 라이브러리 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 회전/왜곡 보정 | ✅ | ❌ | 부분 | ✅ | ✅ |
| 모델 크기 | ~100MB | ~50MB | ~200MB | 클라우드 | 클라우드 |
| 설치 난이도 | 중 | 하 | 하 | 하 | 하 |

**선택 이유**: 오프라인 동작, 무료, 높은 한글 정확도, 영수증 레이아웃 인식 지원.
**단점**: Windows CPU 환경에서 oneDNN 버그 존재 → 아래 섹션 참조.

### 2.3 패키지 설치

```bash
pip install paddleocr paddlex paddlepaddle
pip install python-pptx openpyxl python-docx
```

> 오프라인/사내망 환경은 `docs/사내망_설치_가이드.md` 참조.
> numpy, pillow, opencv 등 하위 의존성은 paddleocr가 자동 설치한다.
> 구형 DOC/PPT/XLS 변환은 LibreOffice 별도 설치 필요 (DOCX/PPTX/XLSX는 불필요).

### 2.4 Windows CPU 환경 주의사항 (oneDNN 버그)

PaddleOCR 3.x는 Windows CPU 모드에서 두 가지 알려진 버그가 있다.
`core/ocr_engine.py`에서 자동으로 우회 처리하므로 별도 조치 불필요.

| 버그 | 증상 | 적용된 우회 방법 |
|------|------|----------------|
| oneDNN 모델 소스 체크 오류 | 초기화 시 `RuntimeError` | 환경변수 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` 설정 |
| `get_default_run_mode` 오류 | `AttributeError` 발생 | 해당 함수를 `"paddle"` 반환으로 monkey-patch |

### 2.5 디렉토리 구조

```
CreditCardVerifier/
├── main.py                     # CLI 진입점
├── config.py                   # 전역 설정 (상수, 경로)
├── inspection_rules.json       # 점검 규칙 정의 문서
│
├── models/                     # 데이터 모델 (dataclass)
│   ├── __init__.py
│   ├── email_data.py           # EmailData, Submitter, Payment 등
│   ├── receipt_data.py         # ReceiptData
│   └── check_result.py         # CheckResult, Violation, CheckStatus
│
├── core/                       # 핵심 처리 로직
│   ├── email_receiver.py       # POP3 메일 자동 수신
│   ├── email_parser.py         # JSON → EmailData
│   ├── receipt_parser.py       # OCR 텍스트 → ReceiptData
│   ├── ocr_engine.py           # PaddleOCR 래퍼 (SSL 우회 패치 포함)
│   ├── attachment_extractor.py # PDF/PPT/Excel/Word → 이미지 추출
│   ├── image_splitter.py       # 투영 프로파일 기반 이미지 분할
│   ├── multi_receipt_ocr.py    # 다중 영수증 OCR 오케스트레이터
│   ├── cross_validator.py      # R01~R15 교차 검증
│   ├── logger.py               # 콘솔 + CSV 로깅
│   └── results_writer.py       # checker results.csv 기록 + 중복 체크
│
├── master/                     # 마스터 데이터 로더
│   └── master_data_loader.py
│
├── notifier/                   # (미사용, 레거시)
│   └── email_notifier.py
│
├── master_data/                # 마스터 데이터 CSV (수동 관리)
│   ├── 대행사_사업자번호.csv
│   └── 원천세_직급.csv
│
├── test_data/                  # 테스트용 샘플 데이터
│   ├── emails/                 # 이메일 JSON (email_*.json)
│   └── receipts/               # Mock 영수증 JSON (receipt_mock_*.json)
│
├── logs/                       # 실행 시 자동 생성
│   ├── checker logs.csv        # 전체 누적 상세 로그
│   └── checker results.csv     # 이메일 단위 처리 결과
│
└── docs/
    └── GUIDE.md                # 이 문서
```

---

## 3. 시스템 아키텍처

### 3.1 전체 처리 흐름

```mermaid
flowchart TD
    A([CLI 실행]) --> B[마스터 데이터 로드\n대행사 BN / 원천세 직급]
    B --> C{처리 모드}

    C -->|--all-emails| D[test_data/emails/*.json\n일괄 처리]
    C -->|--email| E[단일 이메일 처리]
    D --> F[process_single]
    E --> F

    F --> G[EmailParser\nJSON → EmailData]
    G --> H{제목 필터\n포함 여부 확인}
    H -->|불일치| SKIP([SKIP — 처리 생략])
    H -->|일치| I[ReceiptParser]

    I -->|.json| J[Mock JSON 직접 로드]
    I -->|문서 + --use-ocr| D1[AttachmentExtractor\nPDF/PPT/Excel/Word → 이미지]
    D1 --> K1
    I -->|이미지 + --use-ocr| K1[MultiReceiptOCR\n이미지 분할 시도]
    K1 -->|분할 성공 N개| K2[각 crop\nOCREngine 개별 실행]
    K1 -->|분할 실패| K3[전체 OCR 후\n좌표 클러스터링 fallback]
    K2 --> K4[영수증 N건 items 목록]
    K3 --> K4
    K4 --> L[ReceiptParser\nReceiptData 파싱]
    J --> L

    L --> M[CrossValidator\nR01~R15 규칙 적용]
    M --> N[CheckResult\n위반 목록 집계]

    N --> P[write_txt_report\nlogs/reports/*.txt 저장]
    P --> R[results_writer\nchecker results.csv 기록]
    R --> S[logger\nchecker logs.csv 기록]
```

### 3.2 모듈 의존관계

```mermaid
graph LR
    main --> EmailParser
    main --> ReceiptParser
    main --> MultiReceiptOCR
    main --> AttachmentExtractor
    main --> CrossValidator
    main --> results_writer
    main --> logger
    main --> MasterDataLoader

    AttachmentExtractor --> MultiReceiptOCR
    MultiReceiptOCR --> OCREngine
    MultiReceiptOCR --> ImageSplitter

    EmailParser --> EmailData
    ReceiptParser --> ReceiptData
    ReceiptParser --> MasterDataLoader
    CrossValidator --> EmailData
    CrossValidator --> ReceiptData
    CrossValidator --> Violation
    CrossValidator --> MasterDataLoader
    results_writer --> CheckResult
```

---

## 4. 입출력 데이터 명세

### 4.1 이메일 JSON 구조

이메일 JSON은 SAP/NERP에서 내려오는 형식이며, 테스트 시에는 `test_data/emails/`에 직접 작성한다.

```json
{
  "email_id": "EMAIL-2026-0412-001",
  "subject": "[myF] 신용카드 경비 - 강남 한식당 55,000원",
  "samsung_doc_no": "DJ0120260412AA000001",
  "submitted_at": "2026-04-12T10:30:00",
  "submitter": {
    "employee_id": "20191234",
    "knox_id": "cwkim",
    "name": "김철우",
    "department": "DEV팀",
    "department_code": "DEV001",
    "email": "cwkim@samsung.com"
  },
  "approver": {
    "name": "이부장",
    "department": "DEV팀",
    "department_code": "DEV001"
  },
  "payment": {
    "approval_no": "12345678",
    "card_no_masked": "1234-****-****-5678",
    "merchant_name": "강남 한식당",
    "biz_no": "123-45-67890",
    "payment_date": "2026-04-10",
    "posting_date": "2026-04-12",
    "document_date": "2026-04-10",
    "total_amount": 55000,
    "vat_amount": 5000,
    "supply_amount": 50000
  },
  "accounting": {
    "account_code": "복리후생비",
    "account_name": "복리후생비-기타-기타",
    "origin_cost_center": "DEV001",
    "assigned_cost_center": "DEV001",
    "tax_code": "V1",
    "nontax_reason": "해당사항없음",
    "withholding_tax_code": null,
    "industry_code": "식음료"
  },
  "memo": "팀 점심 식사",
  "gift_info": {
    "is_gift": false,
    "unit_price": null,
    "recipients": []
  },
  "attachments": [
    {
      "filename": "영수증1.jpg",
      "type": "receipt_image",
      "withholding_tax_list_included": false
    }
  ],
  "opinion": {
    "submitter_comment": "",
    "approver_comment": ""
  }
}
```

**주요 필드 설명**

| 필드 | 설명 |
|------|------|
| `subject` | 이메일 제목 (없으면 `[결제승인요청] 업체명 금액원`으로 자동 생성) |
| `samsung_doc_no` | 삼성 전표 번호 — 참조용, 중복 점검 없음 |
| `payment.document_date` | 실 결제일 (SAP Document Date) |
| `payment.posting_date` | SAP 전기일 — 이월 판단 기준 |
| `accounting.tax_code` | SAP 세금코드 (`VF` = 이월 예외 처리) |
| `accounting.nontax_reason` | 불공제 사유 (`"해당사항없음"` = 불공제 없음) |
| `accounting.withholding_tax_code` | 원천세 코드 (`1G` / `1Q` / `2C` / `5B` / null) |
| `accounting.industry_code` | 업종 코드 (상품권 판단 등) |
| `attachments[].type` | `receipt_image` / `withholding_list` / `carryover_doc` / `multi_meal_form` / `opinion_doc` / `other` |
| `gift_info.recipients[].rank` | 선물 수령자 직급 (`CL1`~`CL4` / `외국인` / `협력사`) |

### 4.2 Mock 영수증 JSON 구조

OCR 없이 테스트할 때 사용. `test_data/receipts/receipt_mock_*.json`에 저장.

```json
{
  "source_file": "receipt_mock_01.json",
  "merchant": "강남 한식당",
  "biz_no": "123-45-67890",
  "all_biz_nos": ["123-45-67890"],
  "approval_no": "12345678",
  "date": "2026-04-10",
  "transaction_time": "12:30",
  "total": 55000,
  "vat": 5000,
  "supply": 50000,
  "card_no": "1234-****-****-5678",
  "nontax_keywords": [],
  "is_megamart": false,
  "is_openmarket": false,
  "is_gift_shop": false,
  "is_taxi": false,
  "is_holiday": false,
  "raw_text": ""
}
```

### 4.3 마스터 데이터 CSV

**`master_data/대행사_사업자번호.csv`**

```csv
사업자번호,업체명
123-45-00001,BC카드대행
234-56-00002,KB국민카드대행
```

용도: 영수증에 여러 사업자번호가 있을 때 대행사 번호를 제거하고 실거래 사업자번호를 확정한다.

**`master_data/원천세_직급.csv`**

```csv
사번,Knox_ID,이름,부서,직급
20191234,cwkim,김철우,DEV팀,CL3
20180987,leepark,이박준,마케팅팀,CL1
```

용도: 선물 수령자의 직급으로 예상 원천세 코드를 검증한다.

### 4.4 출력 파일

#### `logs/checker logs.csv` — 상세 실행 로그 (누적)

| 컬럼 | 내용 |
|------|------|
| timestamp | 로그 기록 시각 |
| level | DEBUG / INFO / WARNING / ERROR |
| step | PARSE / RECEIPT / CHECK / RESULT / REPORT 등 |
| rule_no | 규칙 번호 (CHECK 단계만) |
| category | 규칙 카테고리 (부가세 / 원천세 등) |
| message | 로그 전문 |

#### `logs/checker results.csv` — 이메일 단위 처리 결과 (누적)

| # | 컬럼명 | 내용 |
|---|--------|------|
| 1 | timestamp | 점검 시각 |
| 2 | 이메일제목 | email.subject |
| 3 | 기안자 | 이름(knox_id) |
| 4 | 삼성전표번호 | samsung_doc_no |
| 5 | NERP_업체명 | payment.merchant_name |
| 6 | NERP_사업자번호 | payment.biz_no |
| 7 | NERP_결제금액 | payment.total_amount |
| 8 | NERP_부가세 | payment.vat_amount |
| 9 | NERP_계정과목 | accounting.account_name |
| 10 | 영수증_가맹점명 | receipt.merchant |
| 11 | 영수증_사업자번호 | receipt.biz_no |
| 12 | 영수증_부가세 | receipt.vat |
| 13~27 | R01_부가세금액 ~ R15_결재권자 | 규칙별 상태 (OK / WARN / FAIL / 공백) |
| 28 | TXT저장 | Y (저장됨) / N |
| 29 | 점검결과 요약 | WARN/FAIL 위반 요약 |

> **규칙 컬럼 값 규칙**: FAIL > WARN > OK 우선순위로 최악 상태를 기록. 해당 없는 규칙은 공백.
> **TXT 저장 위치**: `logs/reports/년월일_기안자ID_삼성전표번호.txt` (이메일 수신일 기준)

---

## 5. 점검 규칙 (R01 ~ R15)

### 5.1 판정 상태 정의

| 상태 | 아이콘 | 의미 | CSV 기록 |
|------|:----:|------|---------|
| `OK` | ✅ | 정상 — 규정 준수 | OK |
| `WARN` | ⚠️ | 주의 — 개선 권고 (TXT 기록) | WARN |
| `FAIL` | ❌ | 실패 — 규정 위반 (TXT 기록) | FAIL |
| `SKIP` | ⏭️ | 건너뜀 — 해당 없음 | 공백 |
| `INFO` | ℹ️ | 참고 정보 | 공백 |

### 5.2 규칙 상세

| R# | 카테고리 | 규칙명 | FAIL 조건 | WARN 조건 | SKIP 조건 |
|----|---------|-------|----------|----------|----------|
| 01 | 부가세 | 부가세 금액 확인 | 이메일 VAT ↔ 영수증 VAT 차이 > 30원 | 영수증 VAT 미확인 | — |
| 02 | 부가세 | 사업자번호 확인 | 사업자번호 불일치 | 영수증 사업자번호 미확인 | 영수증 없음 |
| 03 | 부가세 | 불공제 항목 점검 | 불공제 항목 있는데 사유가 "해당사항없음" | — | — |
| 04 | 부서코드 | 발생/귀속 부서 일치 | 발생부서 ≠ 귀속부서 | — | — |
| 05 | 계정과목 | 마케팅비 기타 확인 | 판매촉진비/광고선전비인데 `-기타-기타` 아님 | — | — |
| 06 | 원천세 | 선물 원천세 코드 | 선물 ≥ 100,000원인데 원천세코드 없음 | 선물 < 100,000원인데 X1 코드 아님 | — |
| 07 | 원천세 | 상품권 원천세 코드 | 상품권인데 원천세코드 없음 | — | 상품권 해당사항 없음 |
| 08 | 이월처리 | 이월 사유서 첨부 | 이월(Doc월 ≠ Post월)인데 사유서 없음 (VF 제외) | — | — |
| 09 | 증빙첨부 | 다인식대 신청양식 | 여비교통비-기타 ≥ 15,000원인데 양식 미첨부 | — | — |
| 10 | 증빙첨부 | 메가마트 영수증 | 메가마트인데 영수증 미첨부 | — | 메가마트 해당없음 |
| 11 | 증빙첨부 | 오픈마켓 세부내역 | 오픈마켓인데 영수증 없거나 카드전표만 첨부 | — | 오픈마켓 해당없음 |
| 12 | 증빙첨부 | 품의서 첨부 | — | 품의 필수 계정인데 품의서 미첨부 | — |
| 13 | 택시비 | 택시비 한도/심야 | 택시비 > 60,000원 | 자정 이전 사용 && 업무목적 미기입 | 비택시 |
| 14 | 휴일사용 | 휴일 업무목적 | — | 휴일 사용 && 업무목적 미기입 | 평일 사용 |
| 15 | 결재권자 | 결재권자 부서 | — | 결재권자 부서 ≠ 기안자 부서·상위조직 | — |

### 5.3 품의서 필수 계정 목록 (`OPINION_REQUIRED_ACCOUNTS`)

```
회의비-기타 / 지급수수료 / 판매촉진비 / 해외출장비
복리후생비 / 행사비 / 사내교육비
```

### 5.4 불공제 키워드 (`NONTAX_KEYWORDS`)

```
골프 / 스크린골프 / 수영장 / 볼링 / 당구 / PC방
상품권 / 화환 / 과일 / 정육 / 꽃
항공 / 철도 / 택시 / 하이패스 / 주차 / 시설공단 / 도시공사
입장권 / 영화 / 공연 / 박물관 / 놀이공원
도서 / 교재 / 간행물 / 선물
```

---

## 6. 실행 방법

### 6.1 CLI 옵션

```
python main.py [OPTIONS]
```

| 옵션 | 타입 | 설명 |
|------|------|------|
| `--fetch-imap` | flag | POP3로 실제 메일 수신 |
| `--max-emails` | int | 수신 최대 메일 수 (기본: 10) |
| `--since-date` | str | 수신 시작 날짜 (형식: YYYY-MM-DD HH:MM:SS) |
| `--subject-filter` | str | 메일 제목 필터 (기본: '[myF] 신용카드 경비') |
| `--email <path>` | str | 단일 이메일 JSON 파일 경로 |
| `--receipt <path> [<path> ...]` | str+ | 영수증 파일 경로 (복수 지정 가능, `.json`=Mock, `.jpg/.png`=OCR) |
| `--use-ocr` | flag | 이미지 영수증 OCR 처리 활성화 |
| `--all-emails` | flag | `test_data/emails/*.json` 전체 일괄 처리 |
| `--mock-receipts` | flag | `test_data/receipts/receipt_mock_*.json` 자동 매칭 |
| `--json` | flag | 결과를 JSON 형식으로 출력 |

### 6.2 실행 예시

```bash
# 0. POP3 메일 수신 모드
# 기본 수신 (4/10 19:00 이후)
python main.py --fetch-imap

# 메일 수신 + OCR 처리
python main.py --fetch-imap --use-ocr

# 최대 메일 수 지정
python main.py --fetch-imap --max-emails 20

# 날짜 지정
python main.py --fetch-imap --since-date "2026-04-01 00:00:00"

# 1. 단일 이메일 + Mock 영수증 1건 (기본 테스트)
python main.py \
  --email test_data/emails/email_normal_01.json \
  --receipt test_data/receipts/receipt_mock_01.json

# 2. 단일 이메일 + 영수증 여러 건 (동일 전표, 복수 영수증)
#    → TXT 파일명: _01.txt, _02.txt ... 순번 접미사 자동 부여
python main.py \
  --email test_data/emails/email_normal_01.json \
  --receipt test_data/receipts/receipt_mock_01.json \
          test_data/receipts/receipt_mock_02.json

# 3. 단일 이메일 + 실제 이미지 OCR (영수증 1건)
python main.py \
  --email test_data/emails/email_normal_01.json \
  --receipt 영수증1.jpg \
  --use-ocr

# 4. 단일 이메일 + 다중 영수증 이미지 OCR (1장에 N건 포함)
#    → ImageSplitter로 자동 분할 후 건별 점검
#    → TXT 파일명: _01.txt, _02.txt, _03.txt ... 순번 접미사 자동 부여
python main.py \
  --email test_data/emails/email_normal_01.json \
  --receipt 영수증3.jpg \
  --use-ocr

# 5. 전체 테스트 데이터 일괄 처리
python main.py --all-emails --mock-receipts

# 6. JSON 출력 (API 연동 등)
python main.py \
  --email test_data/emails/email_vat_violation.json \
  --receipt test_data/receipts/receipt_mock_02.json \
  --json
```

### 6.3 TXT 리포트 저장 위치

점검 실행 시 `logs/reports/` 디렉토리에 자동 저장된다.

```
# 영수증 1건
logs/reports/20260412_cwkim_DJ0120260412AA000001.txt

# 영수증 복수 건 (동일 전표번호, 영수증 N개)
logs/reports/20260412_cwkim_DJ0120260412AA000001_01.txt
logs/reports/20260412_cwkim_DJ0120260412AA000001_02.txt
```

- 영수증 1건: 접미사 없이 `년월일_기안자ID_삼성전표번호.txt` 저장 (기존 호환)
- 영수증 복수 건: `_01`, `_02` ... 두 자리 순번 접미사 자동 부여
- 파일 내용: 원본 이메일 제목·기안자·업체·금액 + **[오류 항목]** (FAIL) + **[보완 필요]** (WARN)

---

## 7. 설정값 참조 (`config.py`)

### 금액 기준

| 상수 | 기본값 | 관련 규칙 | 설명 |
|------|--------|----------|------|
| `VAT_TOLERANCE` | 30원 | R01 | 부가세 허용 오차 |
| `TAXI_MAX_AMOUNT` | 60,000원 | R13 | 택시비 편도 한도 |
| `MULTI_MEAL_MIN` | 15,000원 | R09 | 다인식대 양식 기준 금액 |
| `GIFT_WITHHOLDING_MIN` | 100,000원 | R06 | 원천세 적용 선물 최소 금액 |

### 처리 설정

| 상수 | 기본값 | 설명 |
|------|--------|------|
| `USE_MOCK_EMAIL` | `True` | 미사용 (레거시, 향후 제거 예정) |
| `EMAIL_SUBJECT_FILTER` | `"[myF] 신용카드 경비"` | 처리 대상 이메일 제목 필터 |

### 원천세 코드 매핑 (`RANK_TO_WITHHOLDING_CODE`)

| 직급 | 원천세 코드 | 대상 |
|------|-----------|------|
| CL1, CL2 | 1G | 임원급 |
| CL3, CL4 | 1Q | 일반 직원 |
| 외국인 | 2C | 외국인 임직원 |
| 협력사 | 5B | 협력사·행정사원 |

---

## 8. 코드 명세서

### 8.1 `models/email_data.py`

```
EmailData
├── email_id: str
├── subject: str
├── samsung_doc_no: str          # 삼성 전표 번호 (형식: DJ0120260227BA000074, 중복 점검 키)
├── submitted_at: str
├── submitter: Submitter
│   ├── employee_id: str         # 8자리 (앞자리 0 포함)
│   ├── knox_id: str
│   ├── name: str
│   ├── department: str
│   ├── department_code: str
│   └── email: str
├── approver: Approver
│   ├── name: str
│   ├── department: str
│   └── department_code: str
├── payment: Payment
│   ├── approval_no: str
│   ├── card_no_masked: str
│   ├── merchant_name: str
│   ├── biz_no: str
│   ├── payment_date: str        # YYYY-MM-DD
│   ├── posting_date: str        # SAP Posting date
│   ├── document_date: str       # SAP Document date (실결제일)
│   ├── total_amount: int
│   ├── vat_amount: int
│   └── supply_amount: int
├── accounting: Accounting
│   ├── account_code: str
│   ├── account_name: str        # 예: "복리후생비-기타-기타"
│   ├── origin_cost_center: str
│   ├── assigned_cost_center: str
│   ├── tax_code: str            # SAP 세금코드 (VF=이월예외)
│   ├── nontax_reason: str
│   ├── withholding_tax_code: Optional[str]
│   └── industry_code: str
├── memo: str
├── gift_info: GiftInfo
│   ├── is_gift: bool
│   ├── unit_price: Optional[int]
│   └── recipients: list[dict]   # {employee_id, name, rank}
├── attachments: list[Attachment]
│   ├── filename: str
│   ├── type: str                # receipt_image|withholding_list|carryover_doc|...
│   └── withholding_tax_list_included: bool
└── opinion: dict

메서드:
  has_attachment_type(att_type: str) -> bool
  has_receipt_image() -> bool
```

### 8.2 `models/receipt_data.py`

```
ReceiptData
├── source_file: str
├── merchant: Optional[str]
├── biz_no: Optional[str]            # 대행사 필터 후 확정 사업자번호
├── all_biz_nos: list[str]           # 영수증 내 모든 사업자번호
├── approval_no: Optional[str]
├── date: Optional[str]              # YYYY-MM-DD
├── transaction_time: Optional[str]  # HH:MM (심야 판단)
├── total: Optional[int]
├── vat: Optional[int]
├── supply: Optional[int]
├── card_no: Optional[str]
├── nontax_keywords: list[str]
├── is_megamart: bool
├── is_openmarket: bool
├── is_gift_shop: bool
├── is_taxi: bool
├── is_holiday: bool
└── raw_text: str

클래스 메서드:
  ReceiptData.empty(source_file) -> ReceiptData
```

### 8.3 `models/check_result.py`

```
CheckStatus(str, Enum)
  OK / WARN / FAIL / INFO / SKIP

Violation
├── rule_no: int
├── category: str
├── check_name: str
├── status: CheckStatus
├── message: str
├── email_field: Optional[str]
└── receipt_field: Optional[str]

CheckResult
├── email_id: str
├── subject: str                 # 원본 이메일 제목 ([myF] 신용카드 경비...)
├── submitter_email: str
├── submitter_name: str
└── violations: list[Violation]

메서드:
  has_violation() -> bool              # FAIL/WARN 존재 여부
  summary() -> dict                    # {OK: n, WARN: m, FAIL: k, INFO: 0, SKIP: 0}
  fail_and_warn() -> list[Violation]
```

### 8.4 `core/email_receiver.py`

```python
# POP3 이메일 수신 모듈

def decode_mime_words(header_value: str) -> str
    # MIME 인코딩된 헤더를 디코딩

def load_verified_slips() -> set
    # 이미 검증 완료된 삼성 전표 번호 목록 로드
    # 파일: logs/verified_emails.json

def save_verified_slip(slip_number: str) -> None
    # 검증 완료된 삼성 전표 번호 저장

class POP3EmailReceiver:
    """POP3 이메일 수신 클래스"""

    def __init__(pop3_server, pop3_port, username, password)
        # 기본값: .env 파일에서 로드
        # POP3_SERVER=pop3.samsung.net
        # POP3_PORT=995

    def connect() -> bool
        # POP3 서버 연결 (SSL)

    def disconnect() -> None
        # 연결 종료

    def get_email_body(msg) -> str
        # 이메일 본문 추출 (HTML → 텍스트 변환)

    def get_attachments(msg, download_dir) -> list[dict]
        # 첨부파일 추출 및 저장

    def fetch_emails_by_subject(
        subject_filter: str,      # 제목 필터
        max_emails: int,          # 최대 검색 수
        exclude_verified: bool,   # 검증 완료 메일 제외
        since_date: datetime      # 수신 시작 날짜
    ) -> list[dict]
        # 제목 필터로 이메일 검색
        # 반환: [{email_id, subject, from_name, from_email, date, body,
        #         attachments, basic_info, detail_list, samsung_doc_no}]

    def parse_basic_info(body: str) -> dict
        # 이메일 본문에서 기본 정보 파싱
        # 추출: 삼성 전표 번호, 발생 부서, 비용 귀속 부서, 신청자, 신청 일자

    def parse_detail_info(body: str) -> list[dict]
        # '상세 정보' 섹션 파싱
        # 추출: 승인 번호, 업체, 사업자번호, 업종, 공급가액, 세액, 승인 금액

    def email_to_json(email_info: dict, output_dir: str) -> str
        # 수신한 이메일을 JSON 파일로 저장
        # 저장 경로: temp/emails/email_{timestamp}_{subject}.json

def fetch_credit_card_emails(
    subject_filter: str,
    max_emails: int,
    exclude_verified: bool,
    save_json: bool,
    since_date: datetime
) -> list[dict]
    # 신용카드 경비 이메일 수신 (편의 함수)
```

**환경 설정 (.env)**

```env
# Samsung.net 로그인 설정
SAMSUNG_ID=your_id
SAMSUNG_PASSWORD=your_password

# POP3 메일 수신 설정
POP3_SERVER=pop3.samsung.net
POP3_PORT=995
```

**검증 완료 전표 추적**

```json
// logs/verified_emails.json
{
  "verified_slips": ["DJ0120260331BA000297", ...],
  "last_updated": "2026-04-13T20:00:00"
}
```

### 8.5 `core/email_parser.py`

```python
class EmailParser:

    def parse_json_file(path: str | Path) -> EmailData
        # 파일 읽기 → parse_json() 위임

    def parse_json(data: dict) -> EmailData
        # submitter.employee_id: str.zfill(8) 정규화
        # subject 없으면 "[결제승인요청] {merchant} {amount:,}원" 자동 생성
        # 각 섹션 null-safe 파싱
```

### 8.5 `core/receipt_parser.py`

```python
HOLIDAYS_2026: set[str]      # 공휴일 날짜 집합 (YYYY-MM-DD)

def _is_holiday(date_str: str) -> bool
    # 토/일 + HOLIDAYS_2026 체크

class ReceiptParser:

    def __init__(master_loader=None)

    def parse(items: list[dict], source_file: str) -> ReceiptData
        # OCR [{text, x, y, conf}] → ReceiptData
        # 정규식 추출: 사업자번호 / 승인번호 / 날짜 / 금액 / 카드번호
        # master_loader.filter_actual_biz_nos() 호출
        # NONTAX_KEYWORDS + AI_SUBSCRIPTION_KEYWORDS 검색
        # 업체 분류: is_megamart / is_openmarket / is_gift_shop / is_taxi / is_holiday

    def from_json_file(path: str | Path) -> ReceiptData
        # Mock JSON 직접 로드 (OCR 불필요)
```

**주요 정규식 패턴**

| 추출 항목 | 패턴 예시 |
|----------|----------|
| 사업자번호 | `\d{3}-\d{2}-\d{5}` |
| 거래일시 | `\d{4}[./\-]\d{2}[./\-]\d{2}[\s\-]+\d{2}:\d{2}` |
| 합계금액 | `합\s*계\s*[:：]?\s*([\d,]+)\s*원` |
| 부가세 | `부가세\s*[:：]?\s*([\d,]+)\s*원?` |

### 8.6 `core/ocr_engine.py`

```python
class OCREngine:

    def __init__()
        # self._ocr = None  (지연 초기화)

    def _init() -> None
        # PaddleOCR 모델 초기화 (최초 호출 시만)
        # 모델: PP-OCRv5_mobile_det / korean_PP-OCRv5_mobile_rec
        # use_doc_orientation_classify=True, lang="korean"
        # Windows 버그 우회 2가지 적용

    def run(image_path: str) -> list[dict]
        # 반환: [{text, x, y, conf}] — y좌표 오름차순 정렬
```

### 8.7 `core/cross_validator.py`

```python
class CrossValidator:

    def __init__(master_loader=None)

    def validate(email: EmailData, receipt: Optional[ReceiptData]) -> list[Violation]
        # R01~R15 순차 실행, 모든 Violation 합산 반환

    # 내부 규칙 메서드 (각각 list[Violation] 반환)
    def _check_vat(email, receipt)               # R01
    def _check_biz_no(email, receipt)            # R02
    def _check_nontax(email, receipt)            # R03
    def _check_dept_code(email)                  # R04
    def _check_account(email)                    # R05
    def _check_withholding_tax(email, receipt)   # R06, R07
    def _check_carryover(email)                  # R08
    def _check_attachments(email, receipt)       # R09~R12
    def _check_taxi(email, receipt)              # R13
    def _check_holiday(email, receipt)           # R14
    def _check_approver(email)                   # R15
```

### 8.8 `core/logger.py`

```python
CSV_LOG_FILE = logs/checker logs.csv
CSV_HEADER = [timestamp, level, step, rule_no, category, message]

class _CSVHandler(logging.Handler)
    # 로그 레코드 → CSV 1행 기록 (누적 append)

class _ColorFormatter(logging.Formatter)
    # ANSI 색상 코드 적용

def _parse_message(msg: str) -> tuple[str, str, str]
    # 메시지에서 (step, rule_no, category) 추출
    # "[R03] FAIL [부가세] ..." → ("CHECK", "3", "부가세")
    # "[PARSE] 완료"           → ("PARSE", "", "")

def get_logger(name: str = "checker") -> logging.Logger
    # 콘솔 핸들러: INFO+ / 색상
    # CSV 핸들러: DEBUG+ / 누적 저장
```

### 8.9 `core/results_writer.py`

```python
RESULTS_FILE = logs/checker results.csv
REPORTS_DIR  = logs/reports/
RULE_COLUMNS = [("R01", "R01_부가세금액"), ..., ("R15", "R15_결재권자")]

def _rule_status(result: CheckResult, rule_no: int) -> str
    # FAIL > WARN > OK 우선순위로 최악 상태 반환, 없으면 ""

def _summary_content(result: CheckResult) -> str
    # FAIL/WARN 항목을 "[R01]메시지 / [R03]메시지" 형식으로 요약 (CSV용)

def write_txt_report(email: EmailData,
                     receipt: ReceiptData | None,
                     result: CheckResult,
                     receipt_index: int | None = None) -> Path
    # receipt_index: None=단일 건(접미사 없음), 1이상=복수 건 순번 (_01, _02 ...)
    # 저장 경로: logs/reports/{YYYYMMDD}_{knox_id}_{samsung_doc_no}[_{index:02d}].txt
    # 날짜: email.submitted_at (이메일 수신일)
    # 내용: 기본 정보 헤더 + [오류 항목] FAIL + [보완 필요] WARN
    # 이상 없으면 "모든 점검 항목 통과" 메시지
    # 반환값: 저장된 파일 경로(Path)

def write_result(timestamp, email, receipt, result, txt_saved: bool) -> None
    # 파일 없으면 헤더 먼저 작성, 이후 1행 append
    # txt_saved=True → TXT저장 컬럼에 "Y"

def is_already_processed(samsung_doc_no: str) -> bool
    # checker results.csv에서 삼성전표번호(삼성전표번호 컬럼) 중복 여부 확인
    # samsung_doc_no가 비어있거나 파일 없으면 False 반환
    # 동일 전표번호 발견 시 True → main.py에서 해당 건 SKIP 처리
```

**TXT 파일 구조**

```
============================================================
[신용카드 결제 점검 결과]
============================================================
원본 이메일 : [myF] 신용카드 경비 - 스크린골프존 강남점 110,000원
기안자      : 이박준 (leepark)
업체명      : 스크린골프존 강남점
결제금액    : 110,000원  (부가세 10,000원)
계정과목    : 복리후생비-기타-기타
점검일시    : 2026-04-12 23:42
------------------------------------------------------------
점검 요약   : ✅ 정상 8건  ⚠️  보완필요 1건  ❌ 오류 2건
------------------------------------------------------------

[오류 항목] 2건 — 수정 후 재상신 필요
  ❌ [R01] 부가세 금액 확인
       부가세 불일치: 이메일 10,000원 ↔ 영수증 8,000원 (차이 2000원, 허용 30원)
  ❌ [R03] 부가세 불공제 항목 점검
       불공제 항목 발견(스크린골프)하지만 불공제 사유가 '해당사항없음'임

[보완 필요] 1건 — 확인 및 조치 권고
  ⚠️  [R12] 품의서 첨부 확인
       복리후생비-기타-기타: 품의서(GWP 품의 등) 첨부 필요
============================================================
```

### 8.10 `master/master_data_loader.py`

```python
class MasterDataLoader:

    def __init__(agency_csv: Path, withholding_csv: Path)
        # _agency_biz_nos: set[str]  (정규화된 사업자번호)
        # _employees: list[dict]

    def is_agency_biz_no(biz_no: str) -> bool
        # "-" 제거 후 집합 조회

    def get_employee(employee_id=None, knox_id=None) -> Optional[dict]

    def get_expected_withholding_code(employee_id=None, knox_id=None) -> Optional[str]
        # 직급 → 원천세 코드 변환 (RANK_TO_WITHHOLDING_CODE 참조)

    def filter_actual_biz_nos(all_biz_nos: list[str]) -> list[str]
        # 대행사 BN 제거 후 실거래 BN 목록 반환
```

### 8.11 `main.py`

```python
def print_result(result: CheckResult, use_color: bool = True) -> None
    # FAIL/WARN 우선 정렬 후 ANSI 색상 출력

def process_single(
    email_path: str,
    receipt_path: str,
    master: MasterDataLoader,
    use_ocr: bool = False,
    output_json: bool = False,
    receipt_index: int | None = None,
    ocr_items: list[dict] | None = None,
    receipt_count: int = 1
) -> CheckResult | None
    # None 반환 = 제목 필터 불일치 또는 중복 전표번호 (SKIP)
    # receipt_index: write_txt_report()에 전달 (복수 영수증 시 파일명 접미사)
    # ocr_items: 사전에 추출된 OCR 결과 전달 시 OCR 재실행 생략 (MultiReceiptOCR 연동)
    # 처리 순서:
    #   1. 이메일 파싱
    #   2. 제목 필터 확인 → 불일치 시 None 반환
    #   3. 중복 체크 (samsung_doc_no) → 기처리 건이면 None 반환
    #   4. 영수증 처리: ocr_items 있으면 바로 파싱, 없으면 JSON Mock / OCR
    #   5. 교차 검증 (R01~R15)
    #   6. 콘솔 출력 또는 JSON 출력
    #   7. TXT 리포트 저장 (logs/reports/)
    #   8. checker results.csv 기록

def process_email(
    email_path: str,
    receipt_paths: list[str],
    master: MasterDataLoader,
    use_ocr: bool = False,
    output_json: bool = False
) -> list[CheckResult]
    # 이메일 1건 + 영수증 N건 처리 래퍼
    # 문서 파일(PDF/PPT/Excel/Word): AttachmentExtractor로 이미지 추출 후 재귀 처리
    # 이미지 파일: MultiReceiptOCR로 자동 분할 후 영수증별 process_single() 호출
    # 영수증 2건 이상이면 receipt_index=1,2,..., 1건이면 None (접미사 없음)
    # SKIP(None) 결과 제외 후 list 반환

def main() -> None
    # argparse 처리
    # --fetch-pop3: POP3로 실제 메일 수신 후 처리
    # --receipt: nargs="+" (복수 경로 허용, 이미지/문서 혼용 가능)
    # --all-emails: 배치 처리, process_email([r_path])로 호출, 통계 출력
    # --email: process_email(email, receipt_paths) 호출
```

### 8.12 `core/image_splitter.py`

```python
# 파라미터 상수
WHITE_THRESH  = 200    # 흰색 픽셀 밝기 기준
WHITE_RATIO   = 0.95   # 행/열이 여백으로 판단될 흰색 비율
MIN_GAP_PX    = 30     # 여백으로 인정할 최소 연속 픽셀 수
MIN_REGION_H  = 700    # 수평 분할 후 최소 높이 (미만 시 인접 영역 병합)
MIN_REGION_W  = 200    # 수직 분할 후 최소 너비 (미만 시 인접 영역 병합)

# 내부 헬퍼
def _to_gray(arr) -> np.ndarray
    # BGR/RGB/RGBA → grayscale (가중 평균)

def _content_bounds(proj) -> tuple[int, int]
    # 투영 프로파일에서 컨텐츠 실제 경계 [start, end] 반환

def _find_gaps(proj, start, end) -> list[tuple[int, int, int]]
    # WHITE_RATIO 이상 연속 구간(여백) 탐색, MIN_GAP_PX 이상만 반환
    # 반환: [(gap_start, gap_end, size), ...]

def _adaptive_threshold(gaps) -> int
    # 여백 크기 목록에서 적응형 분할 임계값 계산
    # 전략: 정렬된 gap 크기에서 최대 점프(bimodal 분포 분리) → 큰 그룹 최솟값
    # bimodal 불명확 시 (min+max)/2 fallback, MIN_GAP_FLOOR=60 하한 적용

def _gaps_to_splits(gaps, threshold) -> list[int]
    # 임계값 이상인 여백의 중심점을 분할선으로 반환

def _merge_small_regions(boundaries, min_size) -> list[int]
    # min_size 미만 조각을 인접 영역과 반복 병합

def _split_axis(arr, axis, min_size) -> list[np.ndarray]
    # axis=0: 수평(행) 분할 / axis=1: 수직(열) 분할

class ImageSplitter:

    def split(image_input) -> list[np.ndarray]
        # 진입점: 파일경로(str|Path) 또는 numpy 배열 → 분할된 영수증 목록
        # 내부적으로 _split_2d() 호출

    def _split_2d(arr) -> list[np.ndarray]
        # Step 1: 수평(상하) 분할
        # Step 2: 각 행 내부에서 수직(좌우) 분할
        #   - 수직 분할선이 이미지 중앙 20%~80% 범위에 있어야 유효 (아니면 취소)
```

**분할 전략 요약**

| 단계 | 방향 | 방법 | 과분할 방지 |
|------|------|------|------------|
| Step 1 | 수평 (상→하) | 행별 흰색 비율 투영 | 적응형 임계값 + `MIN_REGION_H=700px` 병합 |
| Step 2 | 수직 (좌→우) | 열별 흰색 비율 투영 | 분할선 중앙 20~80% 범위 검증 + `MIN_REGION_W=200px` 병합 |

### 8.13 `core/multi_receipt_ocr.py`

```python
# fallback 파라미터
CLUSTER_GAP_RATIO = 0.08   # y좌표 gap이 이미지 높이의 이 비율 이상이면 다른 영수증
CLUSTER_X_BIMODAL = 0.15   # x좌표 분포 양측 분리 기준 (이미지 너비 비율)

class MultiReceiptOCR:

    def __init__(ocr_engine: OCREngine)
        # self._ocr: OCREngine
        # self._splitter: ImageSplitter

    def run(image_path: str) -> list[list[dict]]
        # Stage 1: ImageSplitter.split() → 분할 성공 시 각 crop OCR
        #   - 빈 crop(바코드만 등) 제외
        # Stage 2 fallback: 전체 OCR 후 좌표 클러스터링
        #   - _cluster_by_coordinates() 적용
        #   - 클러스터링 실패 시 전체 items 1건으로 반환
        # 반환: list[list[dict]]  # 영수증별 [{text, x, y, conf}] 목록

    def _ocr_array(arr: np.ndarray) -> list[dict]
        # numpy 배열 → 임시 JPEG 파일 저장 → OCREngine.run() → 임시 파일 삭제

    def _cluster_by_coordinates(items, img_h, img_w) -> list[list[dict]]
        # Step A: y좌표 기준 수평 클러스터링 (gap > img_h * CLUSTER_GAP_RATIO)
        # Step B: 각 클러스터 내 x좌표 bimodal 판별 → 좌/우 분리
```

**처리 흐름 (Stage 1 → Stage 2 fallback)**

```
이미지 입력
  │
  ▼
ImageSplitter.split()
  ├─ 분할 N>1 ──→ 각 crop OCR → [items₁, items₂, ..., itemsₙ]  ✅ Stage 1
  └─ 분할 1개 ──→ 전체 이미지 OCR → 좌표 클러스터링              ↩ Stage 2 fallback
                    ├─ 클러스터 발견 → [cluster₁, cluster₂, ...]
                    └─ 클러스터 불가 → [all_items]
```

### 8.14 `core/attachment_extractor.py`

```python
# 지원 형식
SUPPORTED_SUFFIXES = {".pdf", ".pptx", ".xlsx", ".docx", ".ppt", ".xls", ".doc"}
IMAGE_SUFFIXES     = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".gif"}

class NotSupportedError(Exception)
    # 지원 불가 형식 또는 LibreOffice 미설치 시 발생

def extract_images(file_path: str | Path) -> list[Path]
    # 첨부파일에서 영수증 이미지를 추출해 임시 파일로 저장, 경로 목록 반환
    # 구형 포맷(.doc/.ppt/.xls): LibreOffice headless로 변환 후 재귀 처리
    # PDF    : pypdfium2 — 각 페이지를 scale=2 (144 DPI) PNG로 렌더링
    # PPTX   : python-pptx — MSO_SHAPE_TYPE.PICTURE 도형에서 image.blob 추출
    # XLSX   : openpyxl — sheet._images 순회, PIL로 PNG 변환
    # DOCX   : python-docx — part.rels 중 "image" 관계에서 blob 추출
    # 반환값: 임시 파일 경로 목록 (list[Path]) — 사용 후 cleanup_extracted() 호출 필요

def cleanup_extracted(image_paths: list[Path]) -> None
    # extract_images()가 생성한 임시 파일 일괄 삭제 (Path.unlink(missing_ok=True))
```

**LibreOffice 의존성**

| 포맷 | 변환 필요 여부 | 비고 |
|------|:-----------:|------|
| PDF, PPTX, XLSX, DOCX | ❌ | Python 라이브러리로 직접 처리 |
| DOC, PPT, XLS (구형) | ✅ | LibreOffice headless 설치 필요 |

```bash
# LibreOffice 설치 없이 구형 포맷 처리 시 발생하는 오류
NotSupportedError: 구형 포맷(.doc) 변환을 위해 LibreOffice 설치가 필요합니다.
# 설치: https://www.libreoffice.org/download/
```

**임시 파일 경로 규칙**

| 파일 유형 | 임시 디렉토리 접두사 | 파일명 패턴 |
|----------|------------------|-----------|
| PDF 페이지 | `ccv_pdf_*` | `page_001.png`, `page_002.png` … |
| PPTX 이미지 | `ccv_pptx_*` | `slide001_img001.png` … |
| XLSX 이미지 | `ccv_xlsx_*` | `sheet_시트명_img001.png` … |
| DOCX 이미지 | `ccv_docx_*` | `img001.png`, `img002.jpg` … |
| LibreOffice 변환 | `ccv_lo_*` | 변환된 DOCX/PPTX/XLSX |

---

## 9. 파일 명세서

### 9.1 소스 코드 파일

| 파일 경로 | 유형 | 역할 | 주요 클래스 / 함수 |
|----------|------|------|-----------------|
| `main.py` | 진입점 | CLI 파이프라인 오케스트레이터 | `main()`, `process_single()`, `print_result()` |
| `config.py` | 설정 | 전역 상수 및 경로 정의 | 상수 전용 (클래스/함수 없음) |
| `inspection_rules.json` | 문서 | R01~R15 점검 규칙 정의 (JSON) | — |
| `models/email_data.py` | 모델 | 이메일 데이터 구조 | `EmailData`, `Submitter`, `Approver`, `Payment`, `Accounting`, `GiftInfo`, `Attachment` |
| `models/receipt_data.py` | 모델 | OCR 영수증 데이터 구조 | `ReceiptData` |
| `models/check_result.py` | 모델 | 점검 결과 및 상태 열거형 | `CheckResult`, `Violation`, `CheckStatus` |
| `models/__init__.py` | 패키지 | 모델 일괄 export | — |
| `core/email_parser.py` | 로직 | JSON → EmailData 변환 | `EmailParser` |
| `core/receipt_parser.py` | 로직 | OCR 텍스트 → ReceiptData 변환 | `ReceiptParser`, `_is_holiday()` |
| `core/ocr_engine.py` | 로직 | PaddleOCR 래퍼 (Windows 버그 우회) | `OCREngine` |
| `core/image_splitter.py` | 로직 | 투영 프로파일 기반 이미지 분할 | `ImageSplitter`, `_adaptive_threshold()` |
| `core/multi_receipt_ocr.py` | 로직 | 다중 영수증 OCR 오케스트레이터 (분할 + 좌표 클러스터링 fallback) | `MultiReceiptOCR` |
| `core/attachment_extractor.py` | 로직 | PDF/PPT/Excel/Word 첨부파일에서 영수증 이미지 추출 | `extract_images()`, `cleanup_extracted()`, `NotSupportedError` |
| `core/cross_validator.py` | 로직 | R01~R15 교차 검증 | `CrossValidator` |
| `core/logger.py` | 인프라 | 콘솔+CSV 이중 로깅 | `get_logger()`, `_CSVHandler`, `_ColorFormatter` |
| `core/results_writer.py` | 인프라 | TXT 리포트 저장 + checker results.csv 기록 + 중복 체크 | `write_txt_report()`, `write_result()`, `is_already_processed()`, `_rule_status()` |
| `core/__init__.py` | 패키지 | — | — |
| `master/master_data_loader.py` | 데이터 | 대행사·원천세 CSV 로드 및 조회 | `MasterDataLoader` |
| `master/__init__.py` | 패키지 | — | — |
| `notifier/email_notifier.py` | (미사용) | 레거시 — Mock/SMTP 이메일 발송 | `EmailNotifier` |
| `notifier/__init__.py` | 패키지 | — | — |

### 9.2 마스터 데이터 파일

| 파일 경로 | 형식 | 컬럼 | 역할 |
|----------|------|------|------|
| `master_data/대행사_사업자번호.csv` | CSV (UTF-8) | 사업자번호, 업체명 | 영수증 내 대행사 BN 필터링 — 실거래 사업자번호 확정 |
| `master_data/원천세_직급.csv` | CSV (UTF-8) | 사번, Knox_ID, 이름, 부서, 직급 | 선물 수령자 직급 기반 원천세 코드 검증 |

### 9.3 테스트 데이터 파일

| 파일 경로 | 역할 | 주요 점검 포인트 |
|----------|------|----------------|
| `test_data/emails/email_normal_01.json` | 정상 케이스 | 부가세·사업자번호 일치, 품의서 WARN |
| `test_data/emails/email_vat_violation.json` | VAT/불공제 위반 | 스크린골프 불공제 항목, R03 FAIL |
| `test_data/emails/email_withholding_tax.json` | 원천세·이월처리 | 상품권 100k+ 선물, 이월처리 사유서 |
| `test_data/emails/email_ai_sub_ok.json` | AI 구독 정상 | Claude Pro, 지급수수료-기타 + 불공제사유 기타 → R03 OK |
| `test_data/emails/email_ai_sub_violation.json` | AI 구독 위반 | ChatGPT Plus, 복리후생비 계정 오류 → R03 FAIL |
| `test_data/receipts/receipt_mock_01.json` | Mock 영수증 #1 | email_normal_01 대응 |
| `test_data/receipts/receipt_mock_02.json` | Mock 영수증 #2 | email_vat_violation 대응 |
| `test_data/receipts/receipt_mock_03.json` | Mock 영수증 #3 | email_withholding_tax 대응 |
| `test_data/receipts/receipt_mock_ai_ok.json` | Mock 영수증 AI 정상 | email_ai_sub_ok 대응 |
| `test_data/receipts/receipt_mock_ai_violation.json` | Mock 영수증 AI 위반 | email_ai_sub_violation 대응 |

### 9.4 출력 파일 (자동 생성)

| 파일 경로 | 형식 | 생성 시점 | 용도 |
|----------|------|----------|------|
| `logs/checker logs.csv` | CSV (UTF-8-BOM) | 실행 시 자동 생성, 누적 append | 규칙별 상세 실행 로그 |
| `logs/checker results.csv` | CSV (UTF-8-BOM) | 실행 시 자동 생성, 누적 append | 이메일 단위 처리 결과 (29컬럼) |
| `logs/reports/년월일_기안자ID_삼성전표번호.txt` | TXT (UTF-8) | 이메일 처리 시 생성 | 점검 결과 리포트 (오류·보완 항목) |

### 9.5 설정·빌드 파일

| 파일 경로 | 역할 |
|----------|------|
| `requirements.txt` | pip 의존성 패키지 목록 |
| `.gitignore` | Git 추적 제외 규칙 |
| `run.bat` | Windows 일괄 실행 배치 |
| `docs/GUIDE.md` | 이 문서 |

---

## 10. 유지보수 가이드

### 9.1 마스터 데이터 갱신

**대행사 사업자번호 추가/삭제**

`master_data/대행사_사업자번호.csv`를 텍스트 편집기로 직접 수정한다.
변경 즉시 다음 실행부터 반영된다 (실행 중 변경 시 재시작 필요).

**직원 정보 추가**

`master_data/원천세_직급.csv`에 행을 추가한다.
직급 코드는 `CL1 / CL2 / CL3 / CL4 / 외국인 / 협력사` 중 하나여야 한다.

### 9.2 점검 규칙 추가·수정

**임계값 변경**: `config.py`의 상수만 수정한다.

```python
TAXI_MAX_AMOUNT = 60_000  # ← 이 값만 수정
```

**규칙 로직 변경**: `core/cross_validator.py`의 해당 메서드를 수정한다.
**새 규칙 추가** 시 아래 3곳을 함께 수정해야 한다.

| 수정 위치 | 내용 |
|----------|------|
| `core/cross_validator.py` | `_check_rXX()` 메서드 추가 및 `validate()` 내 호출 |
| `core/results_writer.py` | `RULE_COLUMNS`에 `("RXX", "RXX_컬럼명")` 추가 |
| `inspection_rules.json` | 문서화 목적으로 규칙 정의 추가 |

> 규칙 컬럼이 추가되면 `checker results.csv`의 구조가 바뀐다. 기존 파일을 삭제하거나 별도 보관 후 재생성한다.

### 9.3 테스트 데이터 추가

**이메일 JSON 추가** (`test_data/emails/email_*.json`)

- `subject`에 `[myF] 신용카드 경비` 포함 (없으면 제목 필터에서 SKIP)
- `samsung_doc_no` 설정
- 날짜 형식: `YYYY-MM-DD`

**Mock 영수증 JSON 추가** (`test_data/receipts/receipt_mock_*.json`)

`--all-emails --mock-receipts` 사용 시 이메일 파일과 알파벳 순 자동 매칭된다 (1:1).
파일 수가 다르면 초과분은 영수증 없음으로 처리된다.
동일 전표번호에 영수증 여러 건을 처리하려면 `--email`과 `--receipt`를 복수 지정한다.

### 9.4 공휴일 업데이트

`core/receipt_parser.py`의 `HOLIDAYS_2026` 집합을 연도에 맞게 갱신한다.

```python
HOLIDAYS_2026 = {
    "2026-01-01",   # 신정
    # ...
}
```

### 9.5 로그 파일 관리

`logs/` 하위 파일은 **누적 추가 방식**으로 기록된다. 주기적으로 아카이브한다.

```bash
# 월별 아카이브 예시
mv "logs/checker logs.csv"    "logs/archive/checker logs_2026-04.csv"
mv "logs/checker results.csv" "logs/archive/checker results_2026-04.csv"
mv logs/reports/*.txt          logs/archive/reports/
```

다음 실행 시 CSV 파일이 없으면 헤더를 포함하여 자동 재생성된다.
TXT 파일은 실행마다 개별 파일로 생성되며 덮어쓰지 않는다.
