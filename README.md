# 신용카드 영수증 점검 도구

PaddleOCR 기반 오프라인 영수증 자동 점검 CLI 도구.

## 파일 구성

```
CreditCardVerifier/
├── receipt_checker.py    # 메인 CLI 도구
├── inspection_rules.json # 점검 규칙 15개 (점검규칙.jpg 에서 추출)
├── run.bat               # Windows 실행 편의 스크립트
├── pkg files/            # 오프라인 설치용 패키지 백업 (.whl)
├── 점검규칙.jpg           # 원본 점검 규칙 이미지
└── 영수증*.jpg            # 테스트 영수증 이미지
```

## 사용법

```bat
# 단일 파일
run.bat 영수증1.jpg

# 여러 파일
run.bat 영수증1.jpg 영수증3.jpg

# 현재 폴더 전체
run.bat --all

# JSON 출력
run.bat --all --json > result.json

# 색상 없이 출력 (로그 저장 시)
run.bat --all --no-color > result.txt
```

또는 직접:
```bash
python -X utf8 receipt_checker.py --all
```

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
| 11 | 증빙첨부 | 유통업체/오픈마켓 → 영수증 필수 (카드전표 불가) |
| 12 | 증빙첨부 | 회의비·복리후생비 등 → 품의 첨부 필요 |
| 13 | 택시비 | 심야 편도 6만원 이내 |
| 14 | 휴일사용 | 휴일 사용 시 업무 목적 적요 필요 |
| 15 | 결재권자 | 발생부서 소속 결재권자 확인 |

---

## 오류 해결법

### 1. `NotImplementedError: ConvertPirAttribute2RuntimeAttribute`

**원인**: PaddlePaddle 3.x + Windows CPU 환경에서 oneDNN(MKL-DNN) 버그
**해결**: `receipt_checker.py` 상단에 monkey-patch 적용됨 (자동 해결)
```python
# CPU에서 강제로 'paddle' 모드 사용 (mkldnn 비활성화)
def _patched(model_name, device_type):
    return 'paddle' if device_type == 'cpu' else _orig(model_name, device_type)
```

---

### 2. `UnicodeEncodeError: 'cp949' codec can't encode`

**원인**: Windows 콘솔 기본 인코딩이 CP949(EUC-KR)라 한글/이모지 출력 불가
**해결 방법 3가지**:
```bat
# 방법 A: run.bat 사용 (권장) - chcp 65001 자동 설정
run.bat --all

# 방법 B: -X utf8 플래그
python -X utf8 receipt_checker.py --all

# 방법 C: 환경변수 설정 후 실행
set PYTHONUTF8=1
python receipt_checker.py --all
```

---

### 3. `ModuleNotFoundError: No module named 'paddlepaddle'`

**원인**: PaddlePaddle은 `import paddle`로 임포트 (패키지명과 다름)
**확인**:
```bash
python -c "import paddle; print(paddle.__version__)"
```

---

### 4. 오프라인 PC에서 패키지 설치

`pkg files/` 폴더의 .whl 파일 사용:
```bash
pip install --no-index --find-links="pkg files" paddlepaddle paddleocr opencv-python
```
> 주의: Python 3.13 + Windows 64bit 환경 기준으로 다운로드된 패키지임

---

### 5. OCR 모델이 없어서 다운로드 시도 시

모델은 최초 실행 시 자동 다운로드되어 캐시됨:
- 캐시 경로: `C:\Users\{사용자}\.paddlex\official_models\`
- 오프라인 환경에서는 캐시 폴더를 그대로 복사해서 사용 가능

---

### 6. OCR 정확도가 낮은 경우

- 영수증 이미지가 너무 어둡거나 흐릿한 경우 → 전처리 필요
- 회전이 심한 경우 → `use_doc_orientation_classify=True` 기본 적용 중
- 해결되지 않으면 `text_detection_model_name='PP-OCRv5_server_det'` 으로 변경 (더 정확하지만 느림)
  ```python
  # receipt_checker.py get_ocr() 내 변경
  text_detection_model_name='PP-OCRv5_server_det',
  ```

---

### 7. `ValueError: Unknown argument: show_log`

**원인**: PaddleOCR 3.x에서 `show_log` 파라미터 제거됨
**해결**: `receipt_checker.py`는 해당 파라미터를 사용하지 않으므로 문제 없음

---

## 환경 정보

| 항목 | 버전 |
|------|------|
| Python | 3.13.3 (64bit) |
| PaddlePaddle | 3.3.1 (CPU) |
| PaddleOCR | 3.4.0 |
| OpenCV | 4.13.0 |
| OS | Windows 11 |
