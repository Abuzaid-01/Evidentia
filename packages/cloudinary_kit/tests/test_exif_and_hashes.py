from datetime import timedelta

import pytest
from evidentia_cloudinary.admin import hamming_distance, phash_to_int
from evidentia_cloudinary.exif import extract_capture_info, parse_coordinate, parse_exif_datetime


@pytest.mark.parametrize(
    ("value", "ref", "expected"),
    [
        ("28 deg 36' 36.00\" N", None, 28.61),
        ("77 deg 12' 36.00\" E", None, 77.21),
        ("33 deg 52' 0.00\" S", None, -33.8667),
        ("28.61", "N", 28.61),
        ("122.4194", "W", -122.4194),
        (12.5, None, 12.5),
        ("not a coordinate", None, None),
    ],
)
def test_parse_coordinate(value: object, ref: str | None, expected: float | None) -> None:
    result = parse_coordinate(value, ref)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected, abs=1e-3)


def test_exif_datetime_with_offset() -> None:
    parsed = parse_exif_datetime("2026:08:12 11:42:05", "+05:30")
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(hours=5, minutes=30)
    assert (parsed.hour, parsed.minute) == (11, 42)


def test_exif_datetime_garbage() -> None:
    assert parse_exif_datetime("0000:00:00 00:00:00") is None
    assert parse_exif_datetime("") is None


def test_extract_capture_info() -> None:
    info = extract_capture_info(
        {
            "DateTimeOriginal": "2026:08:12 11:42:05",
            "GPSLatitude": "25 deg 45' 0.00\" N",
            "GPSLongitude": "71 deg 23' 24.00\" E",
            "Make": "Google",
            "Irrelevant": "x",
        }
    )
    assert info.capture_time is not None
    assert info.latitude == pytest.approx(25.75)
    assert info.longitude == pytest.approx(71.39)
    assert info.curated == {
        "DateTimeOriginal": "2026:08:12 11:42:05",
        "GPSLatitude": "25 deg 45' 0.00\" N",
        "GPSLongitude": "71 deg 23' 24.00\" E",
        "Make": "Google",
    }


def test_phash_roundtrip_and_distance() -> None:
    a = phash_to_int("ffffffffffffffff")
    b = phash_to_int("fffffffffffffff0")
    assert a == -1  # stored as signed BIGINT
    assert hamming_distance(a, b) == 4  # type: ignore[arg-type]
    assert phash_to_int(None) is None
