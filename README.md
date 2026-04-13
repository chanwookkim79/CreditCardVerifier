# 신용카드 영수증 점검 시스템

POP3 이메일 수신 + PaddleOCR 기반 영수증 자동 점검 CLI 도구.

## 주요 기능

| 기능 | 설명 |
|------|------|
| 이메일 수신 | POP3로 `[myF] 신용카드 경비` 메일 자동 수신 |
| 이메일 파싱 | SAP 이메일 → 구조화된 데이터 변환 |
| 첨부파일 추출 | PDF/PPTX/XLSX/DOCX/DOC/PPT/XLS에서 영수증 이미지 자동 추출 |
| OCR | 영수증 이미지 텍스트 추출 (PaddleOCR, 한글 특화) |
| 교차 검증 | 이메일 본문 ↔ 영수증 15개 규칙 자동 검증 |
| 중복 방지 | 삼성전표번호 기준 기처리 건 자동 스킵 |
| 점검 리포트 | TXT 파일 저장 (`logs/reports/`) |
| 로그 기록 | 상세 로그 CSV + 이메일 단위 결과 CSV |

## 파일 구성

```
CreditCardVerifier/
├── main.py                     # CLI 진입점
├── config.py                   # 전역 설정
├── .env                        # 환경 변수 (계정 정보)
├── inspection_rules.json       # 점검 규칙 15개
│
├── core/                       # 핵심 처리 로직
│   ├── email_receiver.py       # POP3 메일 수신
│   ├── email_parser.py         # JSON → EmailData
│   ├── receipt_parser.py       # OCR 텍스트 → ReceiptData
│   ├── ocr_engine.py           # PaddleOCR 래퍼
│   ├── attachment_extractor.py # PDF/PPT/Excel/Word → 이미지 추출
│   ├── image_splitter.py       # 이미지 분할
│   ├── multi_receipt_ocr.py    # 다중 영수증 OCR
│   ├── cross_validator.py      # R01~R15 교차 검증
│   ├── logger.py               # 콘솔 + CSV 로깅
│   └── results_writer.py       # 결과 저장 + 중복 체크
│
├── models/                     # 데이터 모델
│   ├── email_data.py
│   ├── receipt_data.py
│   └── check_result.py
│
├── master/                     # 마스터 데이터 로더
│   └── master_data_loader.py
│
├── master_data/                # 마스터 데이터 CSV
│   ├── 대행사_사업자번호.csv
│   └── 원천세_직급.csv
│
├── test_data/                  # 테스트 데이터
│   ├── emails/
│   └── receipts/
│
├── logs/                       # 실행 시 자동 생성
│   ├── checker logs.csv
│   ├── checker results.csv
│   └── reports/
│
└── docs/
    ├── GUIDE.md
    └── 사내망_설치_가이드.md
```

## 설치

```bash
pip install paddleocr paddlex paddlepaddle
pip install python-pptx openpyxl python-docx
```

> 사내망(방화벽/SSL 프록시) 환경은 `docs/사내망_설치_가이드.md` 참조.
> 구형 DOC/PPT/XLS 변환은 [LibreOffice](https://www.libreoffice.org/download/) 별도 설치 필요 (DOCX/PPTX/XLSX는 불필요).

## 환경 설정

`.env` 파일 생성:

```env
# Samsung.net 로그인 설정
SAMSUNG_ID=your_id
SAMSUNG_PASSWORD=your_password

# POP3 메일 수신 설정
POP3_SERVER=pop3.samsung.net
POP3_PORT=995

# SMTP 메일 발송 설정
SMTP_SERVER=smtp.samsung.net
SMTP_PORT=587
SMTP_USERNAME=your_id
SMTP_PASSWORD=your_password
SENDER_EMAIL=your_id@samsung.com
RECIPIENT_EMAILS=recipient@samsung.com
```

## 사용법

### POP3 메일 수신 모드

```bash
# 기본 수신
py main.py --fetch-pop3

# 메일 수신 + OCR 처리
py main.py --fetch-pop3 --use-ocr

# 최대 메일 수 지정
py main.py --fetch-pop3 --max-emails 20

# 날짜 지정
py main.py --fetch-pop3 --since-date "2026-04-01 00:00:00"
```

### 로컬 파일 처리 모드

```bash
# 단일 이메일 + Mock 영수증
py main.py --email test_data/emails/email_normal_01.json --receipt test_data/receipts/receipt_mock_01.json

# 단일 이메일 + 실제 이미지 OCR
py main.py --email test_data/emails/email_normal_01.json --receipt 영수증.jpg --use-ocr

# 단일 이메일 + PDF 첨부파일 (영수증 이미지 자동 추출 후 OCR)
py main.py --email test_data/emails/email_normal_01.json --receipt 영수증.pdf --use-ocr

# 단일 이메일 + Excel/Word 첨부파일
py main.py --email test_data/emails/email_normal_01.json --receipt 경비내역.xlsx --use-ocr

# 전체 테스트 데이터 일괄 처리
py main.py --all-emails --mock-receipts

# JSON 출력
py main.py --email test_data/emails/email_vat_violation.json --receipt test_data/receipts/receipt_mock_02.json --json
```

## CLI 옵션

| 옵션 | 타입 | 설명 |
|------|------|------|
| `--fetch-pop3` | flag | POP3로 실제 메일 수신 후 처리 |
| `--max-emails` | int | 수신 최대 메일 수 (기본: 10) |
| `--since-date` | str | 수신 시작 날짜 (형식: YYYY-MM-DD HH:MM:SS) |
| `--subject-filter` | str | 메일 제목 필터 (기본: '[myF] 신용카드 경비') |
| `--email` | str | 이메일 JSON 파일 경로 |
| `--receipt` | str+ | 영수증 파일 경로 — 이미지(`.jpg/.png`), PDF, PPTX, XLSX, DOCX 등 (복수 지정 가능) |
| `--use-ocr` | flag | 이미지/문서 영수증 OCR 처리 활성화 |
| `--all-emails` | flag | 테스트 데이터 전체 처리 |
| `--mock-receipts` | flag | Mock 영수증 자동 매칭 |
| `--json` | flag | JSON 형식 출력 |

## 점검 규칙 (15개)

| No | 카테고리 | 점검 내용 |
|----|---------|---------|
| 1 | 부가세 | 영수증 부가세 금액 일치 여부 (30원 허용) |
| 2 | 실거래사업자번호 | 사업자번호 존재/일치 여부 |
| 3 | 부가세불공제 | 불공제 항목 키워드 탐지 (골프, 상품권, AI구독 등) |
| 4 | 부서코드 | 발생부서 ↔ 비용귀속부서 일치 |
| 5 | 계정과목 | 마케팅비는 기타만 허용 |
| 6 | 원천세 | 10만원 초과 선물 → 원천세 코드 필수 |
| 7 | 원천세 | 상품권 결제 → 원천세 코드 필수 |
| 8 | 이월처리 | Posting/Document 날짜 불일치 시 사유서 첨부 |
| 9 | 증빙첨부 | 여비교통비 15,000원 이상 → 다인식대 신청 양식 |
| 10 | 증빙첨부 | 메가마트/판도라 → 영수증 필수 |
| 11 | 증빙첨부 | 유통업체/오픈마켓 → 영수증 필수 |
| 12 | 증빙첨부 | 회의비·복리후생비 등 → 품의 첨부 필요 |
| 13 | 택시비 | 심야 편도 6만원 이내 |
| 14 | 휴일사용 | 휴일 사용 시 업무 목적 적요 필요 |
| 15 | 결재권자 | 발생부서 소속 결재권자 확인 |

---

## 오류 해결법

### 1. `UnicodeEncodeError`

Windows 콘솔 기본 인코딩이 CP949라 한글/이모지 출력 불가

```bash
# 방법 A: -X utf8 플래그
python -X utf8 main.py --all-emails

# 방법 B: 환경변수 설정
set PYTHONUTF8=1
python main.py --all-emails
```

### 2. `ModuleNotFoundError: No module named 'paddlepaddle'`

```bash
pip install paddlepaddle paddleocr
```

### 3. POP3 연결 실패

- `.env` 파일의 계정 정보 확인
- 네트워크 연결 상태 확인
- POP3 서버 주소/포트 확인

---

## 환경 정보

| 항목 | 버전 |
|------|------|
| Python | 3.13.3 (64bit) |
| PaddlePaddle | 3.3.1 (CPU) |
| PaddleOCR | 3.4.0 |
| OpenCV | 4.13.0 |
| OS | Windows 11 |