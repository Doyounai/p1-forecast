import pytest


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    """ทุก test ใช้ฐานข้อมูลและไฟล์โมเดลชั่วคราว ห้ามแตะ data/ จริง (เคยเขียนทับ data/model.joblib มาแล้ว)"""
    from app import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.sqlite3")
    monkeypatch.setattr(config, "MODEL_PATH", tmp_path / "m.joblib")
    yield
