"""
다중 영수증 OCR 오케스트레이터

흐름:
  1. ImageSplitter로 이미지 분할 (수평→수직 투영 프로파일)
  2. 각 crop에 대해 OCREngine.run() 개별 실행
  3. 분할 결과가 1개뿐이면 → OCR 좌표 클러스터링으로 fallback 재시도
"""

import tempfile
import os
import statistics
from pathlib import Path

import numpy as np
from PIL import Image

from core.image_splitter import ImageSplitter


# ── fallback 파라미터 ──────────────────────────────────────────────────
CLUSTER_GAP_RATIO = 0.08   # y좌표 gap이 이미지 높이의 이 비율 이상이면 다른 영수증
CLUSTER_X_BIMODAL = 0.15   # x좌표 분포가 양쪽으로 나뉘는 기준 (이미지 너비 비율)


class MultiReceiptOCR:
    """
    이미지 1장에서 여러 영수증의 OCR 결과를 추출.

    Parameters
    ----------
    ocr_engine : OCREngine
        초기화된 OCREngine 인스턴스 (재사용하여 모델 로드 1회만).

    Examples
    --------
    >>> from core.ocr_engine import OCREngine
    >>> from core.multi_receipt_ocr import MultiReceiptOCR
    >>> engine = OCREngine()
    >>> multi = MultiReceiptOCR(engine)
    >>> all_items = multi.run("영수증3.jpg")  # list[list[dict]]
    >>> print(len(all_items))  # 3
    """

    def __init__(self, ocr_engine):
        self._ocr = ocr_engine
        self._splitter = ImageSplitter()

    # ── 공개 API ──────────────────────────────────────────────────────

    def run(self, image_path: str) -> list[list[dict]]:
        """
        이미지에서 영수증별 OCR 결과 반환.

        Returns
        -------
        list[list[dict]]
            각 영수증의 OCR 텍스트 목록. 항목 형식:
            {"text": str, "x": float, "y": float, "conf": float}
        """
        # Stage 1: 투영 프로파일 분할
        crops = self._splitter.split(image_path)

        if len(crops) > 1:
            # 분할 성공 → 각 crop 개별 OCR
            results = []
            for crop_arr in crops:
                items = self._ocr_array(crop_arr)
                if items:          # 빈 영역(바코드만 등) 제외
                    results.append(items)
            if results:
                return results

        # Stage 2: fallback — 전체 OCR 후 좌표 클러스터링
        all_items = self._ocr.run(image_path)
        if not all_items:
            return []

        img_h, img_w = self._image_size(image_path)
        clustered = self._cluster_by_coordinates(all_items, img_h, img_w)
        return clustered if clustered else [all_items]

    # ── 내부: crop 배열 OCR ───────────────────────────────────────────

    def _ocr_array(self, arr: np.ndarray) -> list[dict]:
        """numpy 배열을 임시 파일로 저장 후 OCR 실행."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            tmp_path = f.name
        try:
            img = Image.fromarray(arr)
            img.save(tmp_path, "JPEG", quality=95)
            return self._ocr.run(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ── 내부: 좌표 클러스터링 fallback ───────────────────────────────

    @staticmethod
    def _image_size(image_path: str) -> tuple[int, int]:
        img = Image.open(str(image_path))
        w, h = img.size
        return h, w

    def _cluster_by_coordinates(
        self,
        items: list[dict],
        img_h: int,
        img_w: int,
    ) -> list[list[dict]]:
        """
        OCR 텍스트 박스 좌표로 영수증 영역 클러스터링.

        Step A) y좌표 기준 수평 분할
        Step B) 각 수평 클러스터 내에서 x좌표 bimodal 판별로 수직 분할
        """
        if not items:
            return []

        # ── Step A: 수평 클러스터링 ───────────────────────────────
        sorted_by_y = sorted(items, key=lambda i: i["y"])
        gap_thresh_h = img_h * CLUSTER_GAP_RATIO

        h_clusters: list[list[dict]] = []
        current: list[dict] = [sorted_by_y[0]]
        for prev, cur in zip(sorted_by_y, sorted_by_y[1:]):
            if cur["y"] - prev["y"] > gap_thresh_h:
                h_clusters.append(current)
                current = []
            current.append(cur)
        h_clusters.append(current)

        # ── Step B: 수직 분할 (각 수평 클러스터 내부) ─────────────
        results: list[list[dict]] = []
        gap_thresh_v = img_w * CLUSTER_X_BIMODAL

        for cluster in h_clusters:
            xs = [i["x"] for i in cluster]
            if not xs:
                continue

            x_min, x_max = min(xs), max(xs)
            x_mid = img_w / 2

            # x 범위가 이미지 양쪽(left zone + right zone)에 걸치는지 확인
            has_left  = any(x < x_mid - gap_thresh_v * img_w for x in xs)
            has_right = any(x > x_mid + gap_thresh_v * img_w for x in xs)

            if has_left and has_right:
                # 중앙 기준 좌/우 분리
                left  = [i for i in cluster if i["x"] < x_mid]
                right = [i for i in cluster if i["x"] >= x_mid]
                if left:
                    results.append(sorted(left,  key=lambda i: (i["y"], i["x"])))
                if right:
                    results.append(sorted(right, key=lambda i: (i["y"], i["x"])))
            else:
                results.append(cluster)

        return results
