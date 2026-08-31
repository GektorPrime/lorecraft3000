"""Content-addressed image storage service.

Accepts image bytes, verifies/decodes them with Pillow, computes SHA-256 over
the ORIGINAL bytes, stores at <store_root>/<sha256[:2]>/<sha256>.<ext>,
deduplicates (identical bytes never stored twice), writes an atomic JSON
sidecar next to each stored image, and returns metadata for DB pointers.

Image bytes are never stored in SQLite — only the sha256 pointer.
Sidecars contain no secrets.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError


@dataclass(frozen=True)
class StoredImage:
    """Metadata returned for DB pointers after storing an image."""

    sha256: str
    path: str
    size: int
    format: str
    width: int
    height: int
    deduplicated: bool


# Map Pillow format names to file extensions.
_FORMAT_EXT = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
    "GIF": "gif",
    "BMP": "bmp",
    "TIFF": "tiff",
}


class ImageStorageError(Exception):
    """Raised when image bytes cannot be verified or stored."""


class ImageStorage:
    """Content-addressed store rooted at a directory on disk."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def store(self, data: bytes, *, source_name: str | None = None) -> StoredImage:
        """Verify, hash, and store image bytes. Returns metadata.

        Raises ImageStorageError if the bytes are not a decodable image.
        """
        if not data:
            raise ImageStorageError("empty image bytes")

        # Verify/decode with Pillow (also gives us format + dimensions).
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageStorageError(f"not a decodable image: {exc}") from exc

        fmt = (img.format or "PNG").upper()
        ext = _FORMAT_EXT.get(fmt)
        if ext is None:
            raise ImageStorageError(f"unsupported image format: {fmt}")

        # SHA-256 over the ORIGINAL bytes (not the re-encoded image).
        digest = hashlib.sha256(data).hexdigest()

        dest_dir = self.root / digest[:2]
        dest_path = dest_dir / f"{digest}.{ext}"
        sidecar_path = dest_dir / f"{digest}.json"

        deduplicated = dest_path.exists()

        if not deduplicated:
            dest_dir.mkdir(parents=True, exist_ok=True)
            self._atomic_write(dest_path, data)
            self._write_sidecar(sidecar_path, digest, ext, len(data), fmt, source_name)

        return StoredImage(
            sha256=digest,
            path=str(dest_path),
            size=len(data),
            format=fmt,
            width=img.width,
            height=img.height,
            deduplicated=deduplicated,
        )

    def _atomic_write(self, path: Path, data: bytes) -> None:
        """Write bytes atomically (write temp file in same dir, then rename)."""
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _write_sidecar(
        self,
        sidecar_path: Path,
        digest: str,
        ext: str,
        size: int,
        fmt: str,
        source_name: str | None,
    ) -> None:
        """Write the JSON sidecar atomically. No secrets, ever."""
        sidecar = {
            "sha256": digest,
            "extension": ext,
            "size": size,
            "format": fmt,
            "source_name": source_name,
        }
        data = json.dumps(sidecar, indent=2, sort_keys=True).encode("utf-8")
        self._atomic_write(sidecar_path, data)

    def path_for(self, sha256: str, ext: str) -> Path:
        """Return the expected on-disk path for a stored image."""
        return self.root / sha256[:2] / f"{sha256}.{ext}"
