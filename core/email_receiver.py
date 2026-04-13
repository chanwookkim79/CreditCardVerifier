"""POP3 이메일 수신 모듈
삼성 메일 서버에서 신용카드 경비 이메일을 수신하여 처리합니다.
"""

import os
import re
import json
import email
import poplib
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from dotenv import load_dotenv
import datetime as dt

# 환경 변수 로드
load_dotenv()

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent

# 검증 완료된 전표 추적 파일
VERIFIED_EMAILS_FILE = PROJECT_ROOT / "logs" / "verified_emails.json"


def decode_mime_words(header_value: str) -> str:
    """MIME 인코딩된 헤더를 디코딩합니다."""
    if header_value is None:
        return ""
    
    decoded_fragments = decode_header(header_value)
    decoded_string = ""
    
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            if encoding:
                try:
                    decoded_string += fragment.decode(encoding)
                except (LookupError, UnicodeDecodeError):
                    decoded_string += fragment.decode('utf-8', errors='ignore')
            else:
                decoded_string += fragment.decode('utf-8', errors='ignore')
        else:
            decoded_string += str(fragment)
    
    return decoded_string


def load_verified_slips() -> set:
    """이미 검증 완료된 삼성 전표 번호 목록을 로드합니다."""
    verified_slips = set()
    
    try:
        if VERIFIED_EMAILS_FILE.exists():
            with open(VERIFIED_EMAILS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                verified_slips = set(data.get('verified_slips', []))
            print(f"[POP3] 검증 완료된 전표 로드: {len(verified_slips)}개")
    except Exception as e:
        print(f"[POP3] 검증 완료 전표 로드 오류: {e}")
    
    return verified_slips


def save_verified_slip(slip_number: str) -> None:
    """검증 완료된 삼성 전표 번호를 저장합니다."""
    VERIFIED_EMAILS_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    verified_slips = load_verified_slips()
    verified_slips.add(slip_number)
    
    try:
        data = {
            'verified_slips': list(verified_slips),
            'last_updated': datetime.now().isoformat()
        }
        with open(VERIFIED_EMAILS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[POP3] 검증 완료 전표 저장: {slip_number}")
    except Exception as e:
        print(f"[POP3] 검증 완료 전표 저장 오류: {e}")


class POP3EmailReceiver:
    """POP3 이메일 수신 클래스"""
    
    def __init__(
        self,
        pop3_server: str = None,
        pop3_port: int = None,
        username: str = None,
        password: str = None
    ):
        self.pop3_server = pop3_server or os.getenv("POP3_SERVER", "pop3.samsung.net")
        self.pop3_port = pop3_port or int(os.getenv("POP3_PORT", "995"))
        self.username = username or os.getenv("SAMSUNG_ID")
        self.password = password or os.getenv("SAMSUNG_PASSWORD")
        self.pop3 = None
        
    def connect(self) -> bool:
        """POP3 서버에 연결합니다."""
        try:
            print(f"[POP3] 서버 연결 중: {self.pop3_server}:{self.pop3_port}")
            self.pop3 = poplib.POP3_SSL(self.pop3_server, self.pop3_port)
            self.pop3.user(self.username)
            self.pop3.pass_(self.password)
            print("[POP3] 로그인 성공!")
            return True
        except Exception as e:
            print(f"[POP3] 연결 실패: {e}")
            return False
    
    def disconnect(self) -> None:
        """POP3 서버 연결을 종료합니다."""
        try:
            if self.pop3:
                self.pop3.quit()
                print("[POP3] 연결 종료")
        except Exception:
            pass
    
    def get_email_body(self, msg) -> str:
        """이메일 본문을 추출합니다."""
        body = ""
        html_body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                if "attachment" in content_disposition:
                    continue
                
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset()
                        if not charset:
                            try:
                                payload_str = payload.decode('utf-8', errors='ignore')
                                if payload_str.isascii() or any('\uac00' <= c <= '\ud7a3' for c in payload_str):
                                    charset = 'utf-8'
                                else:
                                    charset = 'euc-kr'
                            except:
                                charset = 'utf-8'
                        
                        try:
                            decoded_text = payload.decode(charset, errors='ignore')
                        except (LookupError, UnicodeDecodeError):
                            try:
                                decoded_text = payload.decode('euc-kr', errors='ignore')
                            except:
                                decoded_text = payload.decode('utf-8', errors='ignore')
                        
                        if content_type == "text/plain" and not body:
                            body = decoded_text
                        elif content_type == "text/html" and not html_body:
                            html_body = decoded_text
                except Exception:
                    continue
            
            if not body and html_body:
                body = re.sub(r'<style[^>]*>.*?</style>', '', html_body, flags=re.DOTALL | re.IGNORECASE)
                body = re.sub(r'<!--.*?-->', '', body, flags=re.DOTALL)
                body = re.sub(r'<[^>]+>', ' ', body)
                body = re.sub(r'\s+', ' ', body).strip()
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or 'utf-8'
                    try:
                        body = payload.decode(charset, errors='ignore')
                    except (LookupError, UnicodeDecodeError):
                        try:
                            body = payload.decode('euc-kr', errors='ignore')
                        except:
                            body = payload.decode('utf-8', errors='ignore')
            except Exception:
                pass
        
        return body
    
    def get_attachments(self, msg, download_dir: str = None) -> List[Dict]:
        """이메일 첨부파일을 추출합니다."""
        attachments = []
        
        if download_dir is None:
            download_dir = PROJECT_ROOT / "temp" / "attachments"
        
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    filename = decode_mime_words(filename)
                    filepath = Path(download_dir) / filename
                    
                    payload = part.get_payload(decode=True)
                    if payload:
                        with open(filepath, 'wb') as f:
                            f.write(payload)
                        
                        attachments.append({
                            "filename": filename,
                            "filepath": str(filepath),
                            "size": len(payload)
                        })
        
        return attachments
    
    def fetch_emails_by_subject(
        self,
        subject_filter: str = "[myF] 신용카드 경비",
        max_emails: int = 50,
        exclude_verified: bool = True,
        since_date: datetime = None
    ) -> List[Dict]:
        """제목 필터로 이메일을 검색하여 가져옵니다."""
        if not self.connect():
            return []
        
        try:
            num_messages = len(self.pop3.list()[1])
            print(f"[POP3] 총 메일 개수: {num_messages}")
            
            verified_slips = load_verified_slips() if exclude_verified else set()
            emails = []
            
            start_idx = max(1, num_messages - max_emails + 1)
            
            for i in range(num_messages, start_idx - 1, -1):
                try:
                    response, lines, octets = self.pop3.retr(i)
                    raw_email = b'\r\n'.join(lines)
                    msg = email.message_from_bytes(raw_email)
                    
                    subject = decode_mime_words(msg.get("Subject", ""))
                    
                    if subject_filter and subject_filter not in subject:
                        continue
                    
                    date_str = msg.get("Date", "")
                    if since_date and date_str:
                        try:
                            email_date = parsedate_to_datetime(date_str)
                            if email_date.tzinfo:
                                email_date_utc = email_date.astimezone(dt.timezone.utc).replace(tzinfo=None)
                            else:
                                email_date_utc = email_date
                            if email_date_utc < since_date:
                                continue
                        except Exception as e:
                            print(f"[POP3] 날짜 파싱 오류: {date_str} - {e}")
                    
                    from_header = msg.get("From", "")
                    from_name, from_email = parseaddr(from_header)
                    from_name = decode_mime_words(from_name)
                    
                    body = self.get_email_body(msg)
                    attachments = self.get_attachments(msg)
                    basic_info = self.parse_basic_info(body)
                    
                    slip_number = basic_info.get('삼성 전표 번호', '')
                    if exclude_verified and slip_number and slip_number in verified_slips:
                        print(f"[POP3] ⏭️ 이미 검증된 전표: {slip_number}")
                        continue
                    
                    email_info = {
                        "email_id": str(i),
                        "subject": subject,
                        "from_name": from_name,
                        "from_email": from_email,
                        "date": date_str,
                        "body": body,
                        "attachments": attachments,
                        "basic_info": basic_info,
                        "detail_list": self.parse_detail_info(body),
                        "samsung_doc_no": slip_number
                    }
                    
                    emails.append(email_info)
                    print(f"[POP3] ✅ 메일 수신: {subject[:50]}...")
                    
                except Exception as e:
                    print(f"[POP3] 메일 처리 오류: {e}")
                    continue
            
            return emails
            
        finally:
            self.disconnect()
    
    def parse_basic_info(self, body: str) -> Dict:
        """이메일 본문에서 기본 정보를 파싱합니다."""
        basic_info = {}
        
        patterns = {
            '삼성 전표 번호': r'삼성 전표 번호\s+([A-Z0-9]+)',
            '발생 부서': r'발생 부서\s+([^\s]+)',
            '비용 귀속 부서': r'비용 귀속 부서\s+([^\s]+(?:\/[^\s]+)?)',
            '신청자': r'신청자\s+([^\s]+)',
            '신청 일자': r'신청 일자\s+([\d\.]+)',
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, body)
            if match:
                basic_info[key] = match.group(1).strip()
            else:
                basic_info[key] = ""
        
        draft_match = re.search(r'\d+\s+기안\s+\S+\s+(.+?)\s+\d{4}-\d{2}-\d{2}', body)
        if draft_match:
            basic_info['부서명'] = draft_match.group(1).strip()
        
        return basic_info
    
    def parse_detail_info(self, body: str) -> List[Dict]:
        """이메일 본문에서 '상세 정보' 섹션을 파싱합니다."""
        detail_list = []
        
        sections = re.split(r'(?=상세 정보\s*\(\d+\))', body)
        
        for section in sections:
            if '상세 정보' not in section:
                continue
            
            detail = {}
            
            num_match = re.search(r'상세 정보\s*\((\d+)\)', section)
            if num_match:
                detail['번호'] = num_match.group(1)
            
            patterns = {
                '부서': r'부서\s+([^\s]+(?:\s*[\/\(\)][^\n]+)?)',
                '계정': r'계정\s+([^\s]+)',
                '승인 일시': r'승인 일시\s+([\d\.\s\(\):]+?)(?=\s*승인)',
                '승인 번호': r'승인 번호\s+(\d+)',
                '업체': r'업체\s+([^\n]+?)(?=\s*사업자번호)',
                '사업자번호': r'사업자번호\s+([\d-]+)',
                '업종': r'업종\s+([^\n]+?)(?=\s*업태)',
                '업태': r'업태\s+([^\n]+?)(?=\s*업체\s*주소)',
                '공급가액': r'공급가액\s+([\d,]+)',
                '세액': r'(?<!면)세액\s+([\d,]+)',
                '승인 금액': r'승인 금액\s+([\d,]+)',
                '세금 코드': r'세금 코드\s+([A-Z0-9]+)',
                '불공제 사유': r'불공제 사유\s+([^\n]+?)(?=\s*적요|$)',
                '적요': r'적요\s+([^\n]+?)(?=\s*이동|$)',
            }
            
            for key, pattern in patterns.items():
                match = re.search(pattern, section)
                if match:
                    detail[key] = match.group(1).strip()
                else:
                    detail[key] = ""
            
            if detail.get('승인 번호'):
                detail_list.append(detail)
        
        return detail_list
    
    def email_to_json(self, email_info: Dict, output_dir: str = None) -> str:
        """수신한 이메일을 JSON 파일로 저장합니다."""
        if output_dir is None:
            output_dir = PROJECT_ROOT / "temp" / "emails"
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        basic_info = email_info.get('basic_info', {})
        detail_list = email_info.get('detail_list', [])
        first_detail = detail_list[0] if detail_list else {}
        
        email_data = {
            "email_id": email_info.get('email_id', ''),
            "subject": email_info.get('subject', ''),
            "samsung_doc_no": basic_info.get('삼성 전표 번호', ''),
            "submitted_at": email_info.get('date', ''),
            "submitter": {
                "employee_id": "",
                "knox_id": email_info.get('from_email', '').split('@')[0],
                "name": email_info.get('from_name', ''),
                "department": basic_info.get('부서명', ''),
                "department_code": basic_info.get('발생 부서', ''),
                "email": email_info.get('from_email', '')
            },
            "approver": {"name": "", "department": "", "department_code": ""},
            "payment": {
                "approval_no": first_detail.get('승인 번호', ''),
                "card_no_masked": "",
                "merchant_name": first_detail.get('업체', ''),
                "biz_no": first_detail.get('사업자번호', ''),
                "payment_date": first_detail.get('승인 일시', ''),
                "posting_date": "",
                "document_date": "",
                "total_amount": int(first_detail.get('승인 금액', '0').replace(',', '') or 0),
                "vat_amount": int(first_detail.get('세액', '0').replace(',', '') or 0),
                "supply_amount": int(first_detail.get('공급가액', '0').replace(',', '') or 0)
            },
            "accounting": {
                "account_code": "",
                "account_name": first_detail.get('계정', ''),
                "origin_cost_center": basic_info.get('발생 부서', ''),
                "assigned_cost_center": basic_info.get('비용 귀속 부서', ''),
                "tax_code": first_detail.get('세금 코드', ''),
                "nontax_reason": first_detail.get('불공제 사유', ''),
                "withholding_tax_code": None,
                "industry_code": first_detail.get('업종', '')
            },
            "memo": first_detail.get('적요', ''),
            "gift_info": {"is_gift": False, "unit_price": None, "recipients": []},
            "attachments": [
                {
                    "filename": att['filename'],
                    "type": "receipt" if any(ext in att['filename'].lower() for ext in ['.jpg', '.jpeg', '.png', '.pdf']) else "other",
                    "withholding_tax_list_included": False
                }
                for att in email_info.get('attachments', [])
            ],
            "opinion": {},
            "raw_body": email_info.get('body', ''),
            "detail_list": detail_list
        }
        
        safe_subject = re.sub(r'[^\w\-_.]', '_', email_info.get('subject', 'unknown'))[:50]
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"email_{timestamp}_{safe_subject}.json"
        filepath = Path(output_dir) / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(email_data, f, ensure_ascii=False, indent=2)
        
        print(f"[POP3] JSON 저장: {filepath}")
        return str(filepath)


def fetch_credit_card_emails(
    subject_filter: str = "[myF] 신용카드 경비",
    max_emails: int = 50,
    exclude_verified: bool = True,
    save_json: bool = True,
    since_date: datetime = None
) -> List[Dict]:
    """신용카드 경비 이메일을 수신합니다."""
    receiver = POP3EmailReceiver()
    emails = receiver.fetch_emails_by_subject(
        subject_filter=subject_filter,
        max_emails=max_emails,
        exclude_verified=exclude_verified,
        since_date=since_date
    )
    
    if save_json and emails:
        for email_info in emails:
            receiver.email_to_json(email_info)
    
    return emails


# 테스트 실행
if __name__ == "__main__":
    print("=" * 60)
    print("POP3 이메일 수신 테스트")
    print("=" * 60)
    
    emails = fetch_credit_card_emails(
        subject_filter="[myF] 신용카드 경비",
        max_emails=10,
        exclude_verified=True,
        save_json=True,
        since_date=datetime(2026, 4, 10, 19, 0, 0)
    )
    
    print(f"\n총 {len(emails)}개 메일 수신 완료")
    
    for email_info in emails:
        print(f"\n- 제목: {email_info['subject'][:50]}...")
        print(f"  발신자: {email_info['from_name']} ({email_info['from_email']})")
        print(f"  전표번호: {email_info['samsung_doc_no']}")
        print(f"  상세정보: {len(email_info['detail_list'])}건")
        print(f"  첨부파일: {len(email_info['attachments'])}개")