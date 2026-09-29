from urllib.parse import unquote

from evidentia_cloudinary import CloudinaryCredentials, configure
from evidentia_cloudinary.composite import Side, composite_transformation, composite_url, layer_id

BEFORE = Side("evidentia/org/before-1", (0.02, 0.05, 0.9, 0.88), "BEFORE 12 Aug 2026")
AFTER = Side("after-2", (0.0, 0.0, 1.0, 1.0), "AFTER 20 Sep, 2026 / <x>")


def test_composite_crops_both_sides_and_layers_the_authenticated_after_photo() -> None:
    raw = composite_transformation(BEFORE, AFTER)
    steps = raw.split("/")
    assert steps[0] == "c_crop,x_0.0200,y_0.0500,w_0.9000,h_0.8800"  # floats: relative crop
    assert "l_authenticated:after-2" in steps
    # a full-frame side needs no crop
    layer = steps.index("l_authenticated:after-2")
    assert steps[layer + 1].startswith("c_fill") and steps[layer + 2] == "fl_layer_apply,g_east"
    # the first pad only extends the width: no rescaling of the before panel
    assert "c_pad,w_1616,h_600,g_west,b_white" in steps
    # labels contain only safe characters (commas/slashes would need double escaping)
    assert "l_text:Arial_26_bold:BEFORE%2012%20Aug%202026" in raw
    assert "l_text:Arial_26_bold:AFTER%2020%20Sep%202026%20x" in raw
    assert "pixelate" not in raw


def test_redacted_composite_pixelates_faces_in_both_photos() -> None:
    raw = composite_transformation(BEFORE, AFTER, redact=True)
    assert raw.startswith("e_pixelate_faces:12/c_crop")
    layer = raw.split("/").index("l_authenticated:after-2")
    assert raw.split("/")[layer + 1] == "e_pixelate_faces:12"


def test_composite_url_is_signed_and_names_both_assets() -> None:
    configure(CloudinaryCredentials("demo-cloud", "1234", "s3cr3t"))
    url = composite_url(BEFORE, AFTER)
    assert "/image/authenticated/s--" in url.url  # signed: required for the authenticated layer
    assert unquote(url.url).endswith("evidentia/org/before-1.jpg")
    assert url.transformation in url.url
    assert layer_id("a/b/c") == "a:b:c"
