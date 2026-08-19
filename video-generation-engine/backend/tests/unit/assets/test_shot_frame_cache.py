from app.assets.thumbnails import shot_frame_cache_path
from app.core.config import settings


def test_shot_frame_cache_path_matches_the_asset_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    path = shot_frame_cache_path("proj", "sh_01")
    assert path == tmp_path / "proj" / "cache" / "shot_sh_01.jpg"
