"""PaddleOCR 엔진 (Windows CPU oneDNN 버그 우회 포함)"""
import os
import sys
import warnings

# Windows 콘솔 UTF-8
if sys.stdout.encoding != "utf-8":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
if sys.stderr.encoding != "utf-8":
    sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", buffering=1)

# oneDNN 버그 우회
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
warnings.filterwarnings("ignore")

import paddlex.inference.utils.pp_option as _pp_opt
_orig_run_mode = _pp_opt.get_default_run_mode

def _patched(model_name, device_type):
    return "paddle" if device_type == "cpu" else _orig_run_mode(model_name, device_type)

_pp_opt.get_default_run_mode = _patched

from paddleocr import PaddleOCR


class OCREngine:
    def __init__(self):
        self._ocr = None

    def _init(self) -> None:
        if self._ocr is not None:
            return
        print("OCR 모델 로딩 중...", flush=True)
        self._ocr = PaddleOCR(
            use_doc_orientation_classify=True,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            lang="korean",
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
        )
        print("모델 로딩 완료.", flush=True)

    def run(self, image_path: str) -> list[dict]:
        """OCR 실행 → [{text, x, y, conf}] 리스트 (y순 정렬)"""
        self._init()
        result = self._ocr.ocr(image_path)
        if not result or not result[0]:
            return []
        r = result[0]
        items = []
        for text, score, poly in zip(r["rec_texts"], r["rec_scores"], r["rec_polys"]):
            items.append({
                "text": text,
                "x": float(poly[0][0]),
                "y": float(poly[0][1]),
                "conf": round(float(score), 3),
            })
        items.sort(key=lambda i: (i["y"], i["x"]))
        return items
