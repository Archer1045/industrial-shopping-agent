"""bge-m3 编码封装（进程内单例）。"""
import threading

from sentence_transformers import SentenceTransformer

MODEL_DIR = r"D:\AI\models\bge-m3"

_lock = threading.Lock()
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    with _lock:
        if _model is None:
            _model = SentenceTransformer(MODEL_DIR, device="cuda")
    return _model


def encode(texts, normalize: bool = True):
    if isinstance(texts, str):
        texts = [texts]
    return get_model().encode(
        texts,
        normalize_embeddings=normalize,
        batch_size=16,
        show_progress_bar=False,
    )
