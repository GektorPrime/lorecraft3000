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
import threading
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
        # Serializes provenance read-modify-write so concurrent appends to the
        # same content hash (e.g. two generations producing identical bytes)
        # never lose a record. One lock for the store is plenty at this scale.
        self._provenance_lock = threading.Lock()

    def store(
        self,
        data: bytes,
        *,
        source_name: str | None = None,
        allowed_formats: set[str] | None = None,
    ) -> StoredImage:
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
        if allowed_formats is not None and fmt not in allowed_formats:
            allowed = ", ".join(sorted(allowed_formats))
            raise ImageStorageError(
                f"decoded image format {fmt} is not allowed; use {allowed}"
            )
        ext = _FORMAT_EXT.get(fmt)
        if ext is None:
            raise ImageStorageError(f"unsupported image format: {fmt}")

        # SHA-256 over the ORIGINAL bytes (not the re-encoded image).
        digest = hashlib.sha256(data).hexdigest()

        dest_dir = self.root / digest[:2]
        dest_path = dest_dir / f"{digest}.{ext}"
        sidecar_path = dest_dir / f"{digest}.json"

        # A prior crash can leave an image file without its sidecar (or with a
        # damaged one). Deduplicate only on a COMPLETE object; otherwise finish
        # publishing so the orphan is healed rather than skipped forever.
        deduplicated = self._is_complete(dest_path, sidecar_path)

        if not deduplicated:
            dest_dir.mkdir(parents=True, exist_ok=True)
            self._publish(
                dest_dir, dest_path, sidecar_path, data, digest, ext, fmt, source_name
            )

        return StoredImage(
            sha256=digest,
            path=str(dest_path),
            size=len(data),
            format=fmt,
            width=img.width,
            height=img.height,
            deduplicated=deduplicated,
        )

    def _is_complete(self, dest_path: Path, sidecar_path: Path) -> bool:
        """Return True only if both the image and a valid sidecar are present.

        A valid sidecar is readable JSON whose ``extension`` matches the image
        file. An image without a usable sidecar is treated as incomplete so the
        caller re-publishes and heals it.
        """
        if not dest_path.exists():
            return False
        try:
            metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        extension = metadata.get("extension")
        if not extension:
            return False
        return dest_path.name == f"{dest_path.stem}.{extension}"

    def _publish(
        self,
        dest_dir: Path,
        dest_path: Path,
        sidecar_path: Path,
        data: bytes,
        digest: str,
        ext: str,
        fmt: str,
        source_name: str | None,
    ) -> None:
        """Publish the image and sidecar as a durable unit.

        Both files are written to temporary files, fsynced, then renamed into
        place; finally the directory entry is fsynced. A reader never observes
        an image without its sidecar, and a crash cannot leave a half-published
        pair that survives on stable storage.

        When healing an orphaned image (image present, sidecar missing), the
        image bytes are identical (content-addressed), so re-writing them is
        safe and idempotent.
        """
        sidecar_bytes = self._sidecar_bytes(digest, ext, len(data), fmt, source_name)
        tmp_image = self._write_temp(dest_dir, data)
        try:
            tmp_sidecar = self._write_temp(dest_dir, sidecar_bytes)
        except BaseException:
            self._remove_quietly(tmp_image)
            raise
        try:
            os.replace(tmp_image, dest_path)
            os.replace(tmp_sidecar, sidecar_path)
        except BaseException:
            self._remove_quietly(tmp_image)
            self._remove_quietly(tmp_sidecar)
            raise
        self._fsync_dir(dest_dir)

    def _atomic_write(self, path: Path, data: bytes) -> None:
        """Write bytes atomically and durably (temp file + fsync, then rename).

        Used for single-file updates such as provenance appends. Publishing a
        new image plus sidecar pair uses ``_publish`` instead so the two files
        become visible together.
        """
        tmp = self._write_temp(path.parent, data)
        try:
            os.replace(tmp, path)
        except BaseException:
            self._remove_quietly(tmp)
            raise
        self._fsync_dir(path.parent)

    def _write_temp(self, directory: Path, data: bytes) -> str:
        """Write bytes to a fsynced temp file in ``directory``; return its path."""
        fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            self._remove_quietly(tmp)
            raise
        return tmp

    @staticmethod
    def _fsync_dir(directory: Path) -> None:
        """Fsync a directory so a rename into it survives a crash."""
        try:
            fd = os.open(str(directory), os.O_RDONLY)
        except OSError:
            # Some filesystems disallow opening directories; the rename is still
            # atomic even if the directory entry is not separately fsynced.
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    @staticmethod
    def _remove_quietly(path: str | Path) -> None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    def _sidecar_bytes(
        self,
        digest: str,
        ext: str,
        size: int,
        fmt: str,
        source_name: str | None,
    ) -> bytes:
        """Serialize the JSON sidecar. No secrets, ever."""
        sidecar = {
            "sha256": digest,
            "extension": ext,
            "size": size,
            "format": fmt,
            "source_name": source_name,
        }
        return json.dumps(sidecar, indent=2, sort_keys=True).encode("utf-8")

    def path_for(self, sha256: str, ext: str) -> Path:
        """Return the expected on-disk path for a stored image."""
        self._validate_sha256(sha256)
        return self.root / sha256[:2] / f"{sha256}.{ext}"

    def read(self, sha256: str) -> tuple[bytes, dict]:
        """Read stored bytes and sidecar metadata by content hash."""
        self._validate_sha256(sha256)
        sidecar_path = self.root / sha256[:2] / f"{sha256}.json"
        try:
            metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
            extension = metadata["extension"]
            data = self.path_for(sha256, extension).read_bytes()
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            raise ImageStorageError(f"stored image {sha256} is incomplete: {exc}") from exc
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ImageStorageError(f"stored image {sha256} failed its hash check")
        return data, metadata

    def append_provenance(self, sha256: str, record: dict) -> None:
        """Append a secret-free provenance record to an image sidecar.

        The sidecar is a best-effort mirror; the authoritative provenance lives
        in the ``image_provenance`` database table. The read-modify-write is
        serialized so concurrent appends to the same content hash cannot lose
        a record.
        """
        self._validate_sha256(sha256)
        sidecar_path = self.root / sha256[:2] / f"{sha256}.json"
        with self._provenance_lock:
            try:
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ImageStorageError(f"cannot read sidecar for {sha256}: {exc}") from exc
            provenance = sidecar.setdefault("provenance", [])
            if not isinstance(provenance, list):
                raise ImageStorageError(f"invalid provenance data for {sha256}")
            provenance.append(record)
            self._atomic_write(
                sidecar_path,
                json.dumps(sidecar, indent=2, sort_keys=True).encode("utf-8"),
            )

    @staticmethod
    def _validate_sha256(sha256: str) -> None:
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ImageStorageError("sha256 must be 64 lowercase hexadecimal characters")
