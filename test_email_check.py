"""이메일 확인 테스트 스크립트"""
from core.email_receiver import POP3EmailReceiver, decode_mime_words
from datetime import datetime
import email

receiver = POP3EmailReceiver()
if receiver.connect():
    num_messages = len(receiver.pop3.list()[1])
    print(f'총 메일: {num_messages}개')
    
    # 최신 100개 메일 제목 확인
    for i in range(num_messages, max(1, num_messages - 100), -1):
        response, lines, octets = receiver.pop3.retr(i)
        raw_email = b'\r\n'.join(lines)
        msg = email.message_from_bytes(raw_email)
        subject = decode_mime_words(msg.get("Subject", ""))
        date = msg.get("Date", "")
        date_str = date[:30] if date else "no date"
        print(f"{i}: {subject[:60]}... ({date_str})")
    
    receiver.disconnect()