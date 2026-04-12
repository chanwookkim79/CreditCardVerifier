"""전역 설정"""
from pathlib import Path

BASE_DIR = Path(__file__).parent
MASTER_DIR = BASE_DIR / "master_data"
TEST_DATA_DIR = BASE_DIR / "test_data"

AGENCY_CSV = MASTER_DIR / "대행사_사업자번호.csv"
WITHHOLDING_CSV = MASTER_DIR / "원천세_직급.csv"

VAT_TOLERANCE = 30          # 부가세 허용 오차 (원)
TAXI_MAX_AMOUNT = 60_000    # 택시비 편도 한도 (원)
MULTI_MEAL_MIN = 15_000     # 다인 식대 기준 금액 (원)
GIFT_WITHHOLDING_MIN = 100_000  # 원천세 적용 선물 최소 금액 (원)

USE_MOCK_EMAIL = True       # True: 콘솔 출력 / False: SMTP 실제 발송

# 처리 대상 이메일 제목 필터 (포함 문자열)
EMAIL_SUBJECT_FILTER = "[myF] 신용카드 경비"

OPINION_REQUIRED_ACCOUNTS = [
    "회의비-기타", "지급수수료", "판매촉진비",
    "해외출장비", "복리후생비", "행사비", "사내교육비",
]

RANK_TO_WITHHOLDING_CODE = {
    "CL1": "1G", "CL2": "1G",
    "CL3": "1Q", "CL4": "1Q",
    "외국인": "2C",
    "협력사": "5B",
}

NONTAX_KEYWORDS = [
    "골프", "스크린골프", "수영장", "볼링", "당구", "PC방",
    "상품권", "화환", "과일", "정육", "꽃",
    "항공", "철도", "택시", "하이패스", "주차", "시설공단", "도시공사",
    "입장권", "영화", "공연", "박물관", "놀이공원",
    "도서", "교재", "간행물",
    "선물",
]

AI_SUBSCRIPTION_KEYWORDS = [
    "chatgpt", "ChatGPT", "gemini", "Gemini", "claude", "Claude",
    "openai", "OpenAI", "챗지피티", "AI구독", "AI 구독",
]
