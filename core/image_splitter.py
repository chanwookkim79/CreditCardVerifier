"""
다중 영수증 이미지 분할기

Stage 1 – 수평 투영 프로파일 → 상하 분할
Stage 2 – 수직 투영 프로파일 → 좌우 분할 (각 행 내부)
과분할 방지: 적응형 임계값(median×3) + 최소 높이 병합(MIN_REGION_H)
"""

import statistics
from typing import Optional
import numpy as np


# ── 파라미터 ──────────────────────────────────────────────────────────
WHITE_THRESH   = 200      # 흰색 판별 픽셀 밝기 기준 (0~255)
WHITE_RATIO    = 0.95     # 행/열이 '여백'으로 판단될 흰색 비율
MIN_GAP_PX     = 30       # 여백으로 인정할 최소 연속 픽셀 수
ADAPTIVE_MULT  = 3.0      # 적응형 임계값 = median(gaps) × ADAPTIVE_MULT
MIN_GAP_FLOOR  = 60       # 적응형 임계값 하한 (px)
MIN_REGION_H   = 700      # 분할 후 세로 최소 높이 (이 미만 → 인접 영역 병합, A4 스캔 기준 영수증 1장 최솟값)
MIN_REGION_W   = 200      # 분할 후 가로 최소 너비 (이 미만 → 인접 영역 병합)
MARGIN_RATIO   = 0.04     # 이미지 상하/좌우 마진 비율 (컨텐츠 탐색용)


# ── 헬퍼 ─────────────────────────────────────────────────────────────

def _to_gray(arr: np.ndarray) -> np.ndarray:
    """BGR or RGB → grayscale"""
    if arr.ndim == 2:
        return arr
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    # 가중 평균 (OpenCV BGR 순서도 지원)
    return (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.uint8)


def _content_bounds(proj: np.ndarray) -> tuple[int, int]:
    """투영 프로파일에서 실제 컨텐츠가 있는 구간 [start, end] 반환 (마진 없이 정確한 경계)."""
    length = len(proj)
    content = [i for i, v in enumerate(proj) if v < 0.99]
    if not content:
        return 0, length - 1
    return content[0], content[-1]


def _find_gaps(proj: np.ndarray, start: int, end: int) -> list[tuple[int, int, int]]:
    """
    [start, end] 구간에서 WHITE_RATIO 이상인 연속 구간(여백) 탐색.
    반환: [(gap_start, gap_end, size), ...]  (MIN_GAP_PX 이상만)
    """
    sub   = proj[start:end + 1]
    white = sub >= WHITE_RATIO
    gaps  = []
    in_gap, gs = False, 0
    for i, v in enumerate(white):
        if v and not in_gap:
            in_gap, gs = True, i
        elif not v and in_gap:
            in_gap = False
            size = i - gs
            if size >= MIN_GAP_PX:
                gaps.append((start + gs, start + i - 1, size))
    if in_gap:
        size = len(sub) - gs
        if size >= MIN_GAP_PX:
            gaps.append((start + gs, end, size))
    return gaps


def _adaptive_threshold(gaps: list[tuple[int, int, int]]) -> int:
    """
    여백 크기 목록에서 적응형 분할 임계값 계산.

    전략: 정렬된 gap 크기에서 '가장 큰 불연속 점프'를 찾아
    작은 그룹(영수증 내부 여백)과 큰 그룹(영수증 간 여백)을 분리.
    큰 그룹의 최솟값을 임계값으로 사용.
    모든 gap이 비슷하게 작거나 1개뿐이면 MIN_GAP_FLOOR 반환.
    """
    sizes = sorted(sz for _, _, sz in gaps)
    if not sizes:
        return MIN_GAP_FLOOR
    if len(sizes) == 1:
        return max(sizes[0] - 1, MIN_GAP_FLOOR)

    # 인접 항목 간 점프 크기 계산
    jumps = [(sizes[i + 1] - sizes[i], i) for i in range(len(sizes) - 1)]
    max_jump, max_jump_idx = max(jumps, key=lambda x: x[0])

    # 최대 점프가 충분히 크면 (> 최솟값의 1.5배) bimodal 분포로 판단
    if max_jump > sizes[0] * 1.5:
        threshold = sizes[max_jump_idx + 1]  # 큰 그룹의 첫 번째 값
        return max(threshold, MIN_GAP_FLOOR)

    # bimodal 구분이 불명확 → (min+max)/2 fallback
    midpoint = (sizes[0] + sizes[-1]) / 2
    return max(int(midpoint), MIN_GAP_FLOOR)


def _gaps_to_splits(gaps: list[tuple[int, int, int]], threshold: int) -> list[int]:
    """임계값 이상인 여백의 중심점을 분할선으로 반환."""
    return [(s + e) // 2 for s, e, sz in gaps if sz >= threshold]


def _merge_small_regions(boundaries: list[int], min_size: int) -> list[int]:
    """
    분할 경계로부터 생성되는 영역 중 min_size 미만인 조각을
    인접(더 작은 쪽) 영역과 병합해 경계를 재조정.
    """
    if len(boundaries) <= 2:
        return boundaries

    changed = True
    while changed:
        changed = False
        sizes = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]
        for i, sz in enumerate(sizes):
            if sz < min_size and len(boundaries) > 2:
                # 병합: 해당 경계 제거
                # 첫 번째 조각이면 오른쪽 경계 제거, 마지막이면 왼쪽 경계 제거
                if i == 0:
                    boundaries = [boundaries[0]] + boundaries[2:]
                elif i == len(sizes) - 1:
                    boundaries = boundaries[:-2] + [boundaries[-1]]
                else:
                    # 양쪽 중 더 큰 영역(흡수 가능성 높음)으로 병합
                    if sizes[i - 1] >= sizes[i + 1]:
                        boundaries = boundaries[:i + 1] + boundaries[i + 2:]
                    else:
                        boundaries = boundaries[:i] + boundaries[i + 1:]
                changed = True
                break
    return boundaries


# ── 투영 분할 ─────────────────────────────────────────────────────────

def _split_axis(arr: np.ndarray, axis: int, min_size: int) -> list[np.ndarray]:
    """
    axis=0 → 수평(행) 분할, axis=1 → 수직(열) 분할.
    반환: 분할된 sub-array 목록 (분할 불가 시 원본 1개)
    """
    gray = _to_gray(arr)
    h, w = gray.shape

    if axis == 0:          # 수평: 행별 흰색 비율
        proj    = (gray > WHITE_THRESH).sum(axis=1) / w
        c_start, c_end = _content_bounds(proj)
        dim_size = h
        slicer   = lambda a, s, e: a[s:e, :]
    else:                  # 수직: 열별 흰색 비율
        proj    = (gray > WHITE_THRESH).sum(axis=0) / h
        c_start, c_end = _content_bounds(proj)
        dim_size = w
        slicer   = lambda a, s, e: a[:, s:e]

    gaps      = _find_gaps(proj, c_start, c_end)
    threshold = _adaptive_threshold(gaps)
    splits    = _gaps_to_splits(gaps, threshold)

    # 분할선 없으면 원본 반환
    if not splits:
        return [arr]

    # 경계 정렬 및 소영역 병합
    raw_bounds = [0] + splits + [dim_size]
    bounds     = _merge_small_regions(raw_bounds, min_size)

    return [slicer(arr, bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


# ── 공개 API ─────────────────────────────────────────────────────────

class ImageSplitter:
    """
    영수증 이미지를 개별 영수증 단위의 numpy 배열로 분할.

    사용법:
        splitter = ImageSplitter()
        crops = splitter.split(image_path)  # list[np.ndarray]
    """

    def split(self, image_input) -> list[np.ndarray]:
        """
        이미지를 분할해 영수증 단위 numpy 배열 목록 반환.

        Parameters
        ----------
        image_input : str | Path | np.ndarray
            이미지 파일 경로 또는 이미 로드된 numpy 배열 (H,W,C or H,W).
        """
        arr = self._load(image_input)
        return self._split_2d(arr)

    # ── 내부 ──────────────────────────────────────────────────────────

    @staticmethod
    def _load(image_input) -> np.ndarray:
        if isinstance(image_input, np.ndarray):
            return image_input
        from PIL import Image
        img = Image.open(str(image_input)).convert("RGB")
        return np.array(img)

    def _split_2d(self, arr: np.ndarray) -> list[np.ndarray]:
        """
        Step 1: 수평(상하) 분할
        Step 2: 각 행(row)에 대해 수직(좌우) 분할
                단, 수직 분할선이 이미지 중앙 20%~80% 범위에 있어야 유효
        """
        # Step 1 – 수평 분할
        h_rows = _split_axis(arr, axis=0, min_size=MIN_REGION_H)

        # Step 2 – 각 행 내부에서 수직 분할
        results = []
        for row in h_rows:
            _, row_w = row.shape[:2]
            v_cols = _split_axis(row, axis=1, min_size=MIN_REGION_W)

            # 수직 분할선이 중앙 범위(20%~80%)에 있는지 검증
            if len(v_cols) > 1:
                widths = [c.shape[1] for c in v_cols]
                cumulative = 0
                valid = True
                for idx, cw in enumerate(widths[:-1]):
                    cumulative += cw
                    ratio = cumulative / row_w
                    if not (0.20 <= ratio <= 0.80):
                        valid = False
                        break
                if not valid:
                    v_cols = [row]   # 중앙 범위 벗어난 수직 분할 → 취소

            results.extend(v_cols)

        return results
