# 신용카드 영수증 점검 시스템 — Q&A

> 작성일: 2026-04-15
> 개발 과정에서 논의된 설계 결정 및 기술 질문 정리

---

## 1. 다중 영수증 처리 설계

**Q. 이메일 한 건에 여러 영수증이 있을 때 어떻게 처리해야 하나?**

A. 이메일 1건 = 삼성전표번호 1개, 삼성전표번호 1개 = 영수증 N건 구조로 처리한다.
각 영수증은 개별로 OCR → 파싱 → 교차검증 → TXT 리포트 저장까지 독립적으로 처리된다.
TXT 파일명은 복수 건일 때 `_01`, `_02` 접미사를 자동 부여한다.

```
logs/reports/20260412_cwkim_2600412001.txt      ← 1건
logs/reports/20260412_cwkim_2600412001_01.txt   ← 복수 건
logs/reports/20260412_cwkim_2600412001_02.txt
```

---

**Q. 영수증이 N건일 때 R01(부가세 금액 비교)은 어떻게 처리해야 하나?**

A. 이메일의 부가세 금액은 N건 합산이므로 개별 영수증과 직접 비교하면 항상 불일치가 발생한다.
`receipt_count > 1`이면 금액 비교를 SKIP하고 WARN(수동 확인)으로 처리한다.

```
영수증 3건 합산 전표 — 건별 부가세(5,000원) 수동 확인 필요
(이메일 합산 부가세: 15,000원)
```

R02(사업자번호)~R15는 영수증별 독립 점검을 그대로 유지한다.

---

**Q. 영수증은 승인번호 기준으로 개별 처리해야 한다는 의미는?**

A. 각 영수증은 고유한 승인번호를 가지며 독립된 거래 단위다.
OCR → ReceiptData 파싱 → CrossValidator 검증 → TXT 리포트까지 건별로 수행된다.
이메일 컨텍스트(기안자, 계정과목, 부서 등)는 N건 모두 공유하되,
금액 비교(R01)처럼 합산 기준이 맞지 않는 규칙은 다건 여부를 판단해 처리한다.

---

## 2. 테스트 하네스 (Test Harness)

**Q. 이 프로젝트에 테스트 하네스를 적용할 수 있나?**

A. 적용 가능하며 이 프로젝트 구조에 잘 맞는다. 네 가지 이유가 있다.

| 특성 | 하네스 적합 이유 |
|------|----------------|
| R01~R15 규칙 분리 | 규칙별 독립 단위 테스트 가능 |
| OCR 느리고 비결정적 | Mock/Stub으로 교체 시 빠른 피드백 |
| 정규식 다수 | 경계 케이스 회귀 방지 |
| 파이프라인 구조 | 단계별 독립 테스트 가능 |

---

**Q. 하네스 전/후 차이는 무엇인가?**

A. 코드를 수정할 때 검증 방식이 달라진다.

| 항목 | 하네스 없을 때 | 하네스 있을 때 |
|------|-------------|-------------|
| 검증 방법 | 눈으로 확인 | 자동 비교 |
| 속도 | 건당 30초+ (OCR 필요) | 전체 1~2초 (OCR stub) |
| 커버리지 | 방금 테스트한 것만 | 등록된 전 케이스 |
| 회귀 감지 | 운에 맡김 | 즉시 감지 |
| OCR 필요 여부 | 항상 필요 | 불필요 |

---

**Q. 사용자 입장에서 하네스 전/후 사용 방식이 달라지나?**

A. 달라지지 않는다. 하네스는 개발자(코드 수정자)를 위한 것이지 운영자를 위한 것이 아니다.

- CLI 실행 방법: 동일 (`python main.py --email ... --receipt ...`)
- TXT 리포트, CSV 로그, 콘솔 출력: 전부 그대로

간접적인 효과는 있다. 규칙 수정 후 배포 전에 전 케이스 통과를 확인하므로
"업데이트 후 결과가 이상하다"는 상황이 줄어든다.

---

**Q. 하네스 적용 시 어떤 파일이 새로 생성되나?**

A. 기존 파일은 변경 없이 아래 파일이 새로 추가된다.

```
tests/
├── conftest.py                 ← pytest 공통 픽스처 (MockOCREngine 등)
├── fixtures/                   ← 미리 저장된 OCR 결과 JSON
│   ├── ocr_vat_ok.json
│   ├── ocr_vat_fail.json
│   ├── ocr_vat_7일_오파싱.json
│   ├── ocr_biz_no_ok.json
│   ├── ocr_nontax_golf.json
│   └── ...
├── test_receipt_parser.py      ← 정규식 추출 단위 테스트
├── test_cross_validator.py     ← R01~R15 규칙 단위 테스트
└── test_pipeline.py            ← 전체 흐름 통합 테스트

pytest.ini                      ← pytest 설정
```

---

**Q. 픽스처와 테스트는 어떻게 연결되나?**

A. 픽스처는 고정된 입력값, 테스트 함수는 기대값을 정의하고, 코드가 검증 대상이다.

```
픽스처 (변하지 않음)       테스트 함수 (기대값 정의)     코드 (수정 대상)
────────────────────  →   ──────────────────────── →  ───────────────
ocr_vat_ok.json           assert status == OK          receipt_parser.py
ocr_vat_fail.json         assert status == FAIL        cross_validator.py
ocr_vat_7일_오파싱.json    assert vat is None
```

코드를 수정하면 pytest가 모든 픽스처-테스트 조합을 자동으로 재실행한다.

---

**Q. 픽스처는 기준 변경 시 자동으로 업데이트되나?**

A. 자동 업데이트되지 않으며, 의도적으로 그렇게 설계되어 있다.
픽스처가 자동으로 바뀌면 "기준"이 사라져 하네스의 의미가 없어진다.

| 상황 | 픽스처 | 기대값 | 담당 |
|------|--------|--------|------|
| 코드 버그 수정 | 변경 없음 | 변경 없음 | 코드만 수정 |
| 규칙 기준 변경 | 변경 없음 | 수동 수정 | 사람 |
| 새 입력 형식 추가 | 수동 추가 | 수동 추가 | 사람 |
| OCR 엔진 교체 | 수동 검토 후 갱신 | 경우에 따라 | 사람 |

`pytest-snapshot` / `syrupy` 라이브러리를 쓰면 `--snapshot-update` 명령 한 줄로
스냅샷 갱신이 가능하다 (반자동).

---

## 3. 공개 리소스 활용

**Q. 이 프로젝트에 활용 가능한 공개 skill이나 rule이 있나?**

A. 세 가지 범주로 나뉜다.

**Claude Code Slash 명령 (현재 로드된 skill)**

| 명령 | 이 프로젝트 활용 |
|------|----------------|
| `/simplify` | 규칙 추가 후 cross_validator.py 정리 |
| `/commit` | 작업 후 커밋 메시지 자동 생성 |
| `/review` | 코드 리뷰 |

**CLAUDE.md 행동 규칙 (추가 권장)**

```markdown
- core/cross_validator.py 수정 시 docs/GUIDE.md 8.7 섹션도 함께 수정
- 새 점검 규칙 추가 시 core/results_writer.py RULE_COLUMNS도 함께 추가
- config.py 상수 변경 시 GUIDE.md 7섹션 표도 업데이트
```

**오픈소스 패키지**

| 패키지 | 용도 | 적용 위치 |
|--------|------|----------|
| `rapidfuzz` | 퍼지 문자열 매칭 | 가맹점명·사업자번호 유사도 비교 |
| `freezegun` | 날짜 고정 | R08 이월처리, R14 휴일 테스트 |
| `pytest-mock` | OCREngine stub | 단위 테스트 |
| `pydantic` | 자동 타입 검증 | EmailData, ReceiptData 모델 |
| `rule-engine` | 규칙 외부화 | R01~R15를 JSON/YAML로 분리 |

---

## 4. OCR 품질 개선

**Q. 영수증 이미지 분석 실패 시 자동으로 개선하는 방법이 있나?**

A. 전처리 전략을 순서대로 시도하는 **재시도 루프**를 적용할 수 있다.

```
이미지 입력
    ↓
전략 1: 원본 그대로          → OCR → 파싱 → 성공? ──→ 완료
전략 2: 대비 강화            → OCR → 파싱 → 성공? ──→ 완료
전략 3: 이진화 (Otsu)        → OCR → 파싱 → 성공? ──→ 완료
전략 4: 노이즈 제거 + 선명화  → OCR → 파싱 → 성공? ──→ 완료
전략 5: 2배 업스케일         → OCR → 파싱 → 성공? ──→ 완료
    ↓ 전부 실패
WARN → 수동 확인
```

"성공" 판단 기준은 핵심 필드(부가세, 사업자번호, 합계금액) 중 2개 이상 추출 여부다.
전처리 라이브러리는 이미 설치된 `PIL` + `numpy`로 대부분 구현 가능하다.
온라인 환경이라면 모든 전략 실패 시 Claude Vision API를 마지막 fallback으로 사용할 수 있다.

적용 위치: `core/multi_receipt_ocr.py` → `core/ocr_retry.py` 별도 모듈로 분리 권장.

---

## 5. 자동 실행 및 합의 처리 자동화

**Q. 10분마다 자동 실행해서 이메일 도착 시 영수증 분석 결과를 sender에게 피드백하려면?**

A. 두 가지 구성이 필요하다.

**스케줄러 (자동 실행)**

| 방식 | 특징 |
|------|------|
| Windows Task Scheduler | 단순하고 안정적, PC 켜져 있어야 함 (권장) |
| Python APScheduler | 단일 프로세스, 장기 실행 시 메모리 관리 필요 |

**결과 피드백 구성**

```
POP3 수신 → 중복 체크 → 영수증 분석 → CheckResult
    ↓
이상 없음 → "점검 완료" 메일
이상 있음 → "위반 항목 상세" 메일
    ↓
SMTP → sender 발송
```

구현 순서: 1단계 Task Scheduler 등록 → 2단계 결과 이메일 발송 → 3단계 운영 안정화.

---

**Q. 나는 합의 담당자인데 점검 결과를 합의 의견에 추가해야 한다. SMTP 발송과는 다른 문제 아닌가?**

A. 맞다. SMTP는 새 메일을 보내는 것이고, 합의 의견 입력은 결재 시스템 내부에 텍스트를 넣는 것으로 완전히 다른 문제다.

```
SMTP 발송:   분석 결과 → 새 이메일 작성 → sender에게 발송
합의 처리:   분석 결과 → 결재 시스템 의견란 입력 → 합의 처리
```

합의 처리 방식(이메일 회신, 앱 버튼, 웹 포털 등)에 따라 자동화 전략이 완전히 달라진다.

---

**Q. Knox Approval 별도 앱에서 합의하는데 VBA로 제어할 수 있나?**

A. 불가능하다. 구조적인 문제다.

```
VBA 실행 환경: Windows PC / Microsoft Office
Knox Approval: Android/iOS Knox 보안 컨테이너

→ 완전히 다른 환경 — 연결 방법 없음
```

Knox의 설계 목적 자체가 외부 자동화·해킹 방지이므로 로그인 이후에도 컨테이너 외부에서 제어할 수 없다.

현실적인 대안은 앞단 자동화 최대화 + 사람이 할 부분 최소화다.

```
자동 (시스템): 메일 수신 → 영수증 분석 → 합의 의견 생성 → 클립보드 복사 → 알림
수동 (사람):   Knox Approval 열기 → 붙여넣기 → 합의 버튼 탭 (3번의 탭/클릭)
```

---

**Q. Knox Approval이 PC 웹 브라우저로 접근 가능하다면 자동화할 수 있나?**

A. 가능하다. Playwright 브라우저 자동화를 사용한다.

**인증 전략**: SSO + 2FA는 매번 자동화 불가 → 최초 1회 수동 로그인 후 세션 저장, 이후 재사용.

```python
# 최초 1회: 수동 로그인 후 세션 저장
context.storage_state(path="logs/knox_session.json")

# 이후: 저장된 세션으로 자동 접속
context = browser.new_context(storage_state="logs/knox_session.json")
```

**자동화 흐름**:
```
Knox Approval 웹 접속 (저장 세션)
    ↓
삼성전표번호로 문서 검색
    ↓
합의 의견란 자동 입력
    ↓
[사람] 최종 확인 후 합의 버튼 클릭  ← 책임이 따르므로 최종 제출은 사람이
```

세션 만료 시 클립보드 복사 + 알림으로 자동 fallback 처리한다.

---

## 6. Playwright 기술 사항

**Q. Playwright와 Chrome의 차이점은?**

A. Chrome은 브라우저(도구 자체), Playwright는 Chrome을 조종하는 리모컨이다.

```
Python 코드 → Playwright (제어 명령) → Chrome (실행) → 웹사이트
```

| 항목 | Chrome | Playwright |
|------|--------|-----------|
| 정체 | 웹 브라우저 | 브라우저 자동화 라이브러리 |
| 만든 곳 | Google | Microsoft |
| 하는 일 | 웹페이지 표시 | 브라우저 동작을 코드로 제어 |

Selenium 대비 Playwright의 장점: 속도 빠름, 안정성 높음, 대기 처리 자동, 최신 웹앱 대응.

---

**Q. Playwright에서 화면 전환(1번 화면 → 2번 화면)이 가능한가?**

A. 가능하다. 방법은 3가지다.

**① 버튼/링크 클릭**
```python
page.click("text=합의")
page.wait_for_selector("#opinion_textarea")  # 전환 완료 대기 필수
```

**② URL 직접 이동**
```python
page.goto(f"https://knox-approval.samsung.com/doc/{samsung_doc_no}")
```

**③ 팝업/모달 전환**
```python
with page.expect_popup() as popup_info:
    page.click("#opinion_popup_btn")
popup = popup_info.value
popup.fill("#opinion", text)
```

핵심: 화면 전환 후 반드시 `wait_for_selector()`로 다음 화면 로드를 확인하고 진행해야 한다.

---

**Q. Playwright의 최대 해상도는 고정인가?**

A. 고정이 아니다. 자유롭게 설정 가능하다.

```python
context = browser.new_context(
    viewport={"width": 1920, "height": 1080}  # 원하는 해상도 지정
)

# 실행 중 변경도 가능
page.set_viewport_size({"width": 1280, "height": 720})
```

4K(3840×2160)까지 설정 가능하며 Knox Approval 권장 설정:

```python
browser = p.chromium.launch(headless=False, args=["--start-maximized"])
context = browser.new_context(no_viewport=True, locale="ko-KR",
                               timezone_id="Asia/Seoul")
```

---

**Q. Playwright 화면 자체는 큰데 표시되는 내용이 작고 나머지가 흰 여백인 이유는?**

A. 뷰포트 설정 불일치 또는 deviceScaleFactor 문제다.

| 원인 | 해결 |
|------|------|
| viewport가 작게 고정됨 | `viewport={"width": 1920, "height": 1080}`으로 확대 |
| deviceScaleFactor=2 | `device_scale_factor=1`로 고정 |
| 창 크기 < 뷰포트 | `no_viewport=True` + `--start-maximized` |

현재 뷰포트 크기 확인:
```python
size = page.viewport_size
print(f"현재 뷰포트: {size['width']} x {size['height']}")
```
