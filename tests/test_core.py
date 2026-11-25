import asyncio
import time
import cv2
import numpy as np
import pytest
from arabic_lens.models import Rect, TextBlock
from arabic_lens.config import Settings, SettingsService, protect_secret
from arabic_lens.text import normalize, TextFilterService, group_lines
from arabic_lens.storage import TranslationStore
from arabic_lens.detection import RegionTracker, TextRegionDetector
from arabic_lens.translation import TranslationService, validate_endpoint, TranslationError
from arabic_lens.hotkeys import parse_shortcut
from arabic_lens.overlay import place_overlay


@pytest.mark.parametrize("text", [" Continue! ", "CONTINUE", "continue…", "EXIT GAME.", "  Quit   Game! "])
def test_ignore_labels(text):
    assert TextFilterService(Settings()).reason(TextBlock(text, Rect(0, 0, 90, 20))) == "simple UI label"


def test_meaningful_sentence_is_not_filtered():
    f = TextFilterService(Settings())
    assert not f.reason(TextBlock("Continue through the tunnel until you reach the village.", Rect(0, 0, 500, 50)))
    assert not f.reason(TextBlock("Save the villagers before the gate closes.", Rect(0, 0, 500, 50)))
    assert f.reason(TextBlock("%%% $$$ 12!", Rect(0, 0, 50, 20)))
    assert f.reason(TextBlock("You should find the key.", Rect(0, 0, 50, 20), .1)) == "low confidence"


def test_normalization_preserves_meaningful_punctuation():
    assert normalize(" You\nDON’T have  enough money. ") == normalize("you don't have enough money")
    assert normalize("Leave?") != normalize("Leave!")
    assert normalize("1.5 gold") != normalize("15 gold")


def test_cache_history_limits_and_restart(tmp_path):
    s = Settings(cache_limit=2, history_limit=2)
    path = tmp_path / "test.db"
    db = TranslationStore(path, s)
    for i in range(4):
        db.put(f"Sentence {i}.", f"عربي {i}")
        db.record(f"Sentence {i}.", f"عربي {i}", "Game")
    assert db.get("SENTENCE   3") == "عربي 3"
    assert db.get("Sentence 0") is None
    assert len(db.history()) == 2
    assert len(db.history("Sentence 3")) == 1
    s.history_enabled = False
    db.record("Private", "خاص", "Game")
    assert len(db.history()) == 2
    db.close()
    db = TranslationStore(path, s)
    assert db.get("Sentence 3.") == "عربي 3"
    db.clear("cache")
    assert db.get("Sentence 3") is None
    db.close()


def test_translation_gate_and_cache(tmp_path):
    class Provider:
        calls = 0
        async def translate(self, text):
            self.calls += 1
            await asyncio.sleep(.01)
            return "عليك العثور على المفتاح."
    async def scenario():
        store = TranslationStore(tmp_path / "cache.db", Settings())
        provider = Provider()
        service = TranslationService(provider, store)
        first, second = await asyncio.gather(service.translate("Find the key."), service.translate("find  the key"))
        assert first[0] == second[0]
        assert second[1]
        assert provider.calls == 1
        store.close()
    asyncio.run(scenario())


def test_tracker_stability_change_and_disappearance():
    tracker = RegionTracker()
    image = np.zeros((150, 400, 4), dtype=np.uint8)
    rect = Rect(30, 40, 250, 35)
    tracker.update([rect], image, 1)
    assert not tracker.ready(1.4, 650, 100, 3)
    region = tracker.ready(1.7, 650, 100, 3)[0]
    region.processed = True
    tracker.update([Rect(32, 41, 250, 35)], image, 1.8)
    assert region.rect == rect
    assert not tracker.ready(2, 650, 100, 3)
    image[40:75, 30:280] = 200
    assert tracker.update([rect], image, 2.2) == [region.id]
    assert not region.processed
    assert not tracker.ready(2.4, 650, 100, 3)
    assert tracker.ready(2.9, 650, 100, 3)
    assert tracker.update([], image, 3.5) == [region.id]
    assert not tracker.regions


def test_group_lines_context_without_cross_column_merge():
    lines = [TextBlock("You need to", Rect(20, 30, 150, 20)), TextBlock("find the key", Rect(20, 55, 160, 20)), TextBlock("Other dialogue", Rect(400, 30, 150, 20))]
    result = group_lines(lines)
    assert len(result) == 2
    assert result[0].text == "You need to find the key"


def test_detector_finds_text_in_fixture():
    image = np.zeros((720, 1280, 4), dtype=np.uint8)
    cv2.putText(image, "You need to find the key before sunset.", (210, 550), cv2.FONT_HERSHEY_SIMPLEX, .9, (255, 255, 255, 255), 2)
    regions = TextRegionDetector().detect(image)
    assert any(r.y <= 550 and r.bottom >= 550 and r.w > 350 for r in regions)


def test_overlay_clamps_secondary_monitor_and_avoids_others():
    screen = Rect(-1920, 0, 1920, 1080)
    source = Rect(-1000, 950, 400, 80)
    first = place_overlay(source, 500, 90, screen, [])
    assert first.y < source.y
    second = place_overlay(source, 500, 90, screen, [first])
    assert not first.overlap(second)
    assert screen.intersect(second) == second


def test_dpapi_and_settings_round_trip(tmp_path):
    service = SettingsService(tmp_path)
    secret = protect_secret("test credential")
    assert secret != "test credential"
    assert protect_secret(secret, decrypt=True) == "test credential"
    service.settings.api_key = secret
    service.settings.language = "ar"
    service.save()
    loaded = SettingsService(tmp_path).settings
    assert loaded.language == "ar"
    assert loaded.api_key == secret
    assert "test credential" not in service.path.read_text()


@pytest.mark.parametrize("url", ["http://example.com/v1", "https://key:secret@example.com", "file:///test", "https://example.com/?key=abc"])
def test_insecure_endpoints_rejected(url):
    with pytest.raises(TranslationError):
        validate_endpoint(url)


def test_local_endpoint_and_hotkeys():
    validate_endpoint("http://localhost:11434/v1")
    validate_endpoint("https://api.example.com/v1")
    assert parse_shortcut("Alt+Q") == (1, 81)
    assert parse_shortcut("Ctrl+Shift+F5") == (6, 116)
    assert parse_shortcut("Win+Alt+Q") == (9, 81)
    with pytest.raises(ValueError):
        parse_shortcut("Q")
    with pytest.raises(ValueError):
        parse_shortcut("Alt+F4")
