"""점검 결과 데이터 구조"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CheckStatus(str, Enum):
    OK   = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"
    SKIP = "SKIP"


@dataclass
class Violation:
    rule_no: int
    category: str
    check_name: str
    status: CheckStatus
    message: str
    email_field: Optional[str] = None
    receipt_field: Optional[str] = None


@dataclass
class CheckResult:
    email_id: str
    subject: str
    submitter_email: str
    submitter_name: str
    violations: list = field(default_factory=list)

    def has_violation(self) -> bool:
        return any(v.status in (CheckStatus.FAIL, CheckStatus.WARN) for v in self.violations)

    def summary(self) -> dict:
        counts = {s.value: 0 for s in CheckStatus}
        for v in self.violations:
            counts[v.status.value] += 1
        return counts

    def fail_and_warn(self) -> list:
        return [v for v in self.violations if v.status in (CheckStatus.FAIL, CheckStatus.WARN)]
