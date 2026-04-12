"""마스터 데이터 로더 - 대행사 사업자번호 CSV, 원천세 직급 CSV"""
import csv
from pathlib import Path
from typing import Optional
from config import RANK_TO_WITHHOLDING_CODE


class MasterDataLoader:
    def __init__(self, agency_csv: str | Path, withholding_csv: str | Path):
        self._agency_biz_nos: set[str] = set()
        self._employees: list[dict] = []
        self._load_agency(Path(agency_csv))
        self._load_withholding(Path(withholding_csv))

    def _load_agency(self, path: Path) -> None:
        if not path.exists():
            print(f"[WARN] 대행사 CSV 없음: {path}")
            return
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                normalized = row["사업자번호"].replace("-", "").strip()
                self._agency_biz_nos.add(normalized)

    def _load_withholding(self, path: Path) -> None:
        if not path.exists():
            print(f"[WARN] 원천세 직급 CSV 없음: {path}")
            return
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                self._employees.append({
                    "employee_id": row.get("사번", "").strip().zfill(8),
                    "knox_id": row.get("Knox_ID", "").strip().lower(),
                    "name": row.get("이름", "").strip(),
                    "department": row.get("부서", "").strip(),
                    "rank": row.get("직급", "").strip(),
                })

    def is_agency_biz_no(self, biz_no: str) -> bool:
        normalized = biz_no.replace("-", "").strip()
        return normalized in self._agency_biz_nos

    def get_employee(self, employee_id: str = None, knox_id: str = None) -> Optional[dict]:
        """사번 또는 Knox ID로 직원 정보 조회"""
        for emp in self._employees:
            if employee_id and emp["employee_id"] == employee_id.strip().zfill(8):
                return emp
            if knox_id and emp["knox_id"] == knox_id.strip().lower():
                return emp
        return None

    def get_expected_withholding_code(self, employee_id: str = None, knox_id: str = None) -> Optional[str]:
        emp = self.get_employee(employee_id=employee_id, knox_id=knox_id)
        if not emp:
            return None
        return RANK_TO_WITHHOLDING_CODE.get(emp["rank"])

    def filter_actual_biz_nos(self, all_biz_nos: list[str]) -> list[str]:
        """대행사 사업자번호를 제외한 실거래 사업자번호 목록 반환"""
        return [bn for bn in all_biz_nos if not self.is_agency_biz_no(bn)]
