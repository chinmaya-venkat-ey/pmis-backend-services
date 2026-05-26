"""
paddle_server.py
Tiny FastAPI wrapper around PaddleOCR.
Exposed at http://paddleocr:8002 inside Docker network.
"""
import io
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="PaddleOCR Service")

# Lazy-load OCR so the health check works before the model is ready
_ocr = None

def get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    return _ocr


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ocr")
async def ocr_image(file: UploadFile = File(...)):
    """
    POST an image file (jpg, png, pdf page, etc.)
    Returns list of detected text blocks with bounding boxes and confidence.
    """
    try:
        contents = await file.read()
        import numpy as np
        from PIL import Image

        image = Image.open(io.BytesIO(contents)).convert("RGB")
        img_array = np.array(image)

        result = get_ocr().ocr(img_array, cls=True)

        # Flatten result into a clean list
        blocks = []
        if result and result[0]:
            for line in result[0]:
                bbox, (text, confidence) = line
                blocks.append({
                    "text": text,
                    "confidence": round(confidence, 4),
                    "bbox": bbox,
                })

        return JSONResponse({"blocks": blocks, "count": len(blocks)})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
