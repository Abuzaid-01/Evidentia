import httpx
import pytest
import respx
from evidentia_cloudinary import CloudinaryCredentials
from evidentia_cloudinary.analyze import (
    AnalyzeClient,
    caption_text,
    general_responses,
    source_uri,
    structured_prompt,
    tagged_names,
)
from evidentia_cloudinary.errors import CloudinaryPermanentError, CloudinaryRetryableError

CREDS = CloudinaryCredentials("demo", "key", "secret")
BASE = "https://api.cloudinary.com/v2/analysis/demo/analyze"


@respx.mock
def test_captioning_parses_documented_envelope() -> None:
    route = respx.post(f"{BASE}/captioning").mock(
        return_value=httpx.Response(
            200,
            json={
                "limits": {"addons_quota": [{"type": "x", "remaining": 498}]},
                "request_id": "r1",
                "data": {"analysis": {"data": {"caption": "Pink dahlias."}, "model_version": 4}},
            },
        )
    )
    result = AnalyzeClient(CREDS).captioning(source_uri("https://img"))
    assert caption_text(result) == "Pink dahlias."
    assert result.model_version == "4"
    assert result.quota[0]["remaining"] == 498
    assert route.calls[0].request.headers["authorization"].startswith("Basic ")


@respx.mock
def test_tagging_and_general_helpers() -> None:
    respx.post(f"{BASE}/ai_vision_tagging").mock(
        return_value=httpx.Response(
            200, json={"data": {"analysis": {"tags": [{"name": "excavation"}]}}}
        )
    )
    respx.post(f"{BASE}/ai_vision_general").mock(
        return_value=httpx.Response(
            200, json={"data": {"analysis": {"responses": [{"value": '{"a":1}'}]}}}
        )
    )
    client = AnalyzeClient(CREDS)
    tags = client.ai_vision_tagging(source_uri("u"), [{"name": "excavation", "description": "?"}])
    assert tagged_names(tags) == ["excavation"]
    assert general_responses(client.ai_vision_general(source_uri("u"), ["p"])) == ['{"a":1}']


def test_tag_definition_limit() -> None:
    with pytest.raises(ValueError):
        AnalyzeClient(CREDS).ai_vision_tagging(
            source_uri("u"), [{"name": str(i), "description": ""} for i in range(11)]
        )


@respx.mock
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, CloudinaryRetryableError),
        (503, CloudinaryRetryableError),
        (403, CloudinaryPermanentError),
    ],
)
def test_error_mapping(status: int, error: type[Exception]) -> None:
    respx.post(f"{BASE}/captioning").mock(
        return_value=httpx.Response(status, json={"error": {"message": "no"}})
    )
    with pytest.raises(error):
        AnalyzeClient(CREDS).captioning(source_uri("u"))


def test_structured_prompt_uses_json_fence() -> None:
    prompt = structured_prompt("Describe", {"type": "object"})
    assert prompt.startswith("Describe\n```json\n")
    assert prompt.endswith("\n```")
