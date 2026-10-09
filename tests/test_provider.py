import asyncio
import json
import httpx
import pytest
from arabic_lens.config import Settings, protect_secret
from arabic_lens.translation import HttpTranslationProvider, TranslationError


def test_chat_request_arabic_and_text_only():
    async def scenario():
        settings = Settings(endpoint="https://translator.example/v1", model="arabic-model", api_key=protect_secret("fake-test-key"))
        provider = HttpTranslationProvider(settings)
        await provider.client.aclose()
        def respond(request):
            assert request.url.path == "/v1/chat/completions"
            assert request.headers["Authorization"] == "Bearer fake-test-key"
            body = json.loads(request.content)
            assert "Modern Standard Arabic" in body["messages"][0]["content"]
            assert body["messages"][1]["content"] == "Find the key."
            assert "image" not in request.content.decode()
            return httpx.Response(200, json={"choices": [{"message": {"content": "اعثر على المفتاح."}}]})
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        assert await provider.translate("Find the key.") == "اعثر على المفتاح."
        await provider.close()
    asyncio.run(scenario())


def test_azure_request_direction():
    async def scenario():
        settings = Settings(provider="Azure Translator", endpoint="https://translator.example", api_key=protect_secret("fake"), azure_region="westeurope")
        provider = HttpTranslationProvider(settings)
        await provider.client.aclose()
        def respond(request):
            assert request.url.params["from"] == "en"
            assert request.url.params["to"] == "ar"
            assert request.headers["Ocp-Apim-Subscription-Region"] == "westeurope"
            assert json.loads(request.content) == [{"Text": "Find the key."}]
            return httpx.Response(200, json=[{"translations": [{"text": "اعثر على المفتاح.", "to": "ar"}]}])
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        assert await provider.translate("Find the key.") == "اعثر على المفتاح."
        await provider.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("status,body,code", [(429, {}, "rate_limit"), (401, {}, "provider_setup"), (500, {}, "translation_failed"), (200, {"choices": []}, "translation_failed"), (200, {"choices": [{"message": {"content": "English explanation"}}]}, "translation_failed")])
def test_provider_errors_are_short_codes(status, body, code):
    async def scenario():
        provider = HttpTranslationProvider(Settings(endpoint="https://translator.example/v1", model="test"))
        await provider.client.aclose()
        provider.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)))
        with pytest.raises(TranslationError) as exc:
            await provider.translate("Find the key.")
        assert exc.value.code == code
        await provider.close()
    asyncio.run(scenario())
