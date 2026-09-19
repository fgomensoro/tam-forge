from __future__ import annotations


def test_excerpt_key_is_scoped_by_class_owner_clip_and_hash() -> None:
    from tamforge_backend.shadowing.service import excerpt_object_key
    from tamforge_backend.storage.models import validate_object_key

    digest = "a" * 64
    key = excerpt_object_key(owner_id=3, clip_id=41, sha256=digest)

    assert key == f"shadowing-excerpt/3/clip-41/{digest}"
    assert validate_object_key(key) == key
    assert key != excerpt_object_key(owner_id=4, clip_id=41, sha256=digest)
    assert key != excerpt_object_key(owner_id=3, clip_id=42, sha256=digest)
