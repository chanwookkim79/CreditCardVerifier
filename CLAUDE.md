# CreditCardVerifier 프로젝트 컨텍스트

## 프로젝트 목적
삼성전자 신용카드 결제 문서(SAP/myF)의 영수증을 자동 OCR·점검하고,
합의 담당자(나)가 Knox Approval 웹에서 합의 의견을 입력하는 과정을 자동화한다.

## 현재 완성된 기능
- PaddleOCR 기반 영수증 이미지 OCR (오프라인, Windows CPU)
- 이미지 분할: `core/image_splitter.py` — 투영 프로파일 기반, 1장에 N건 자동 분할
- 다중 영수증 OCR: `core/multi_receipt_ocr.py` — 분할 + 좌표 클러스터링 fallback
- R01~R15 교차 검증: `core/cross_validator.py`
- POP3 메일 자동 수신: `core/email_receiver.py`
- 문서 첨부파일 이미지 추출: `core/attachment_extractor.py`
- 중복 전표 스킵: `core/results_writer.py` — `is_already_processed()`
- TXT 리포트 저장: `logs/reports/년월일_기안자ID_전표번호[_01].txt`

## 미구현 (다음 작업)
1. `core/opinion_formatter.py` — CheckResult → 합의 의견 텍스트 생성
2. `core/knox_approval.py` — Playwright로 Knox Approval 웹 자동화
3. `core/ocr_retry.py` — 이미지 전처리 재시도 루프 (분석 실패 대응)
4. Windows Task Scheduler 등록 — 10분 자동 실행
5. `tests/` — 테스트 하네스 (pytest + MockOCREngine)

## 핵심 설계 결정 (변경 시 이유 필요)
- **R01 다건 처리**: 영수증 N건이면 이메일 금액은 합산 → 개별 비교 불가 → `receipt_count > 1`이면 WARN(수동 확인)으로 처리
- **합의 자동화**: Knox Approval 모바일 앱은 자동화 불가 / PC 웹 브라우저 접근 가능 → Playwright 사용
- **인증 전략**: SSO+2FA 자동화 불가 → 최초 1회 수동 로그인 후 세션 저장(`logs/knox_session.json`), 이후 재사용
- **최종 합의 버튼**: 책임이 따르므로 자동 제출 금지 — 의견 입력까지만 자동화, 제출은 사람이
- **오프라인 필수**: Claude Vision API 사용 불가, PaddleOCR만 사용
- **승인번호 기준**: 영수증은 승인번호 기준으로 개별 처리

## 코드 수정 규칙
- `core/cross_validator.py` 수정 시 → `docs/GUIDE.md` 8.7 섹션 동시 수정
- 새 점검 규칙 추가 시 → `core/results_writer.py` RULE_COLUMNS도 함께 추가
- `config.py` 상수 변경 시 → `docs/GUIDE.md` 7섹션 표 업데이트
- 모듈 추가 시 → `docs/GUIDE.md` 3.2(의존관계), 9.1(파일 명세) 업데이트
- 코드 변경과 GUIDE.md 수정은 반드시 같은 커밋에 포함

## 절대 하지 말 것
- `process_single()` 직접 호출 금지 → 반드시 `process_email()` 경유
- OCR 실행 없이 정규식 패턴만 수정하지 말 것 (실제 영수증으로 검증 필요)
- Knox Approval 합의 버튼 자동 클릭 금지
- `--no-verify` 등 git hook 우회 금지

## 기술 환경
- Python 3.13, Windows 11
- PaddleOCR 3.x (oneDNN 버그 → `core/ocr_engine.py`에서 자동 우회)
- 모델 캐시: `C:\Users\cwkim\.paddlex\official_models\`
- 오프라인 설치 가이드: `docs/사내망_설치_가이드.md`

## 주요 문서
- `docs/GUIDE.md` — 전체 시스템 설계 및 코드 명세
- `docs/QnA.md` — 개발 과정 기술 Q&A 누적
- `docs/사내망_설치_가이드.md` — 오프라인 환경 설치
