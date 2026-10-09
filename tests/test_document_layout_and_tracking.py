import asyncio
import time
from pathlib import Path
import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from arabic_lens.config import Settings
from arabic_lens.models import Rect, TextBlock, Translation
from arabic_lens.text import TextFilterService, group_lines, align_list_columns
from arabic_lens.formatting import values, preserves_values
from arabic_lens.translation import TranslationService
from arabic_lens.storage import TranslationStore
from arabic_lens.engine import Engine
from arabic_lens.anchors import VisualAnchors
from arabic_lens.overlay import OverlayManager
import arabic_lens.engine as engine_module

FIXTURES = Path(__file__).parent / 'fixtures'


def wait(qt, predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qt.processEvents()
        if predicate(): return
        # QTest's native wait can hold the GIL and starve background imports.
        # Pump Qt then yield Python's worker threads, as the real event loop does.
        time.sleep(.01)
    raise AssertionError('Document pipeline did not complete')


def test_paragraphs_lists_columns_and_short_words():
    blocks = [TextBlock('A sentence that wraps', Rect(10,10,190,16)),
              TextBlock('onto this line.', Rect(10,34,150,16)),
              TextBlock('Another paragraph.', Rect(10,82,180,16)),
              TextBlock('• Solana: $7.0 billion (35x)', Rect(10,130,200,16)),
              TextBlock('• Cursor: $3 billion (15,000x)', Rect(10,154,240,16))]
    result = align_list_columns(group_lines(blocks))
    assert len(result) == 4
    assert result[0].text == 'A sentence that wraps onto this line.'
    assert result[2].rect.right == result[3].rect.right
    filter = TextFilterService(Settings())
    for word in ['Go','Up','Hat','Warm','Key']:
        assert not filter.reason(TextBlock(word, Rect(0,0,50,20)))
    assert filter.reason(TextBlock('Exit', Rect(0,0,50,20))) == 'simple UI label'
    assert not filter.reason(TextBlock('Estimated Portfolio Value: $206,000,000,000', Rect(0,0,320,14)))


def test_hard_line_breaks_bullets_values_and_cache_repair(tmp_path):
    async def run():
        settings = Settings(); store = TranslationStore(tmp_path/'format.db', settings)
        class Provider:
            calls = 0
            async def translate(self, text):
                self.calls += 1
                # Deliberately omit a value to exercise conservative recovery.
                return 'نص عربي' if '$' in text else 'ترجمة عربية'
        provider = Provider(); service = TranslationService(provider, store)
        source = 'Introduction.\n\n• Amount: $7.0 billion (35x)\n• Total: $206,000,000,000\n\nEnd.'
        store.put(source, 'نص قديم بلا تنسيق')
        result, cached = await service.translate(source)
        assert not cached and result.count('\n') == source.count('\n')
        assert result.splitlines()[2].startswith('• ')
        assert preserves_values(source, result)
        count = provider.calls
        assert (await service.translate(source)) == (result, True)
        assert provider.calls == count
        store.close()
    asyncio.run(run())


def test_cache_keeps_different_paragraph_boundaries(tmp_path):
    store = TranslationStore(tmp_path/'boundaries.db', Settings())
    try:
        store.put('First sentence.\nSecond sentence. Third sentence.', 'الأولى\nالثانية والثالثة')
        assert store.get('First sentence. Second sentence.\nThird sentence.') is None
        assert store.get('first sentence.\n  Second sentence.   Third sentence.')
    finally:
        store.close()


def test_numeric_direction_only_affects_display():
    from arabic_lens.formatting import display_values
    source = 'القيمة: $206,000,000,000 ونسبة 35x ومدة 73 ساعة'
    shown = display_values(source)
    assert '\u2066$206,000,000,000\u2069' in shown
    assert shown.replace('\u2066','').replace('\u2069','') == source


def test_friendly_settings_toggles_and_draft(tmp_path):
    from arabic_lens.ui import SettingsWindow
    from arabic_lens.localization import LocalizationService
    qt = QApplication.instance() or QApplication([])
    settings = Settings(); store = TranslationStore(tmp_path/'settings.db', settings)
    window = SettingsWindow(settings, LocalizationService(settings), store)
    try:
        window.show(); window.navigate(2); qt.processEvents()
        from PySide6.QtWidgets import QLabel
        setup = next(item for item in window.findChildren(QLabel) if item.text() == 'Translation setup')
        built_in = next(item for item in window.findChildren(QLabel) if item.text() == 'Built-in Arabic translation')
        translator = next(item for item in window.findChildren(QLabel) if item.text() == 'Translator')
        assert setup.parentWidget() is built_in.parentWidget()
        assert translator.parentWidget() is window.translation_input.parentWidget()
        assert translator.parentWidget() is not setup.parentWidget()
        assert 0 <= window.builtin_toggle.x() - built_in.geometry().right() <= 20
        assert window.builtin_toggle.isChecked() and not window.provider_toggle.isChecked()
        window.builtin_toggle.setChecked(False); qt.processEvents()
        assert window.provider_toggle.isChecked() and window.translation_advanced.isVisible()
        assert window.fields['provider'].currentData() == 'Chat compatible'
        window.provider_toggle.setChecked(False); qt.processEvents()
        assert window.builtin_toggle.isChecked() and not window.translation_advanced.isVisible()
        window.translation_input.setPlainText('First paragraph.\n\nSecond paragraph with 73 hours.')
        window.navigate(3); qt.processEvents()
        assert not window.watch_advanced.isVisible() and 'min_chars' not in window.fields
        window.navigate(2); qt.processEvents()
        assert window.translation_input.toPlainText().count('\n') == 2
    finally:
        window.hide(); window.deleteLater(); store.close()


@pytest.mark.parametrize('fixture,count', [('paragraphs.png',3),('financial-list.png',8)])
@pytest.mark.parametrize('mode', ['manual','watch'])
def test_attached_screenshots_real_ocr_and_model(monkeypatch, tmp_path, fixture, count, mode):
    qt = QApplication.instance() or QApplication([])
    image = cv2.imread(str(FIXTURES/fixture),cv2.IMREAD_COLOR)
    class Capture:
        def capture(self, rect): return image.copy()
        def close(self): pass
    monkeypatch.setattr(engine_module,'CaptureService',Capture)
    monkeypatch.setattr(engine_module,'PreviewCaptureService',Capture)
    settings = Settings(); store = TranslationStore(tmp_path/'document.db', settings)
    engine = Engine(settings,store)
    results, errors = [], []
    engine.translated.connect(results.append)
    engine.status.connect(lambda code: errors.append(code) if code not in ['ready','reading','translating'] else None)
    bounds = Rect(0,0,image.shape[1],image.shape[0])
    try:
        if mode == 'manual':
            engine.translate_region(bounds,'Document')
            wait(qt,lambda: len(results)>=count)
        else:
            # The same Watch processing path used for a stable detector crop.
            from arabic_lens.detection import TrackedRegion, fingerprint
            region = TrackedRegion('fixture',bounds,fingerprint(image),time.monotonic(),time.monotonic())
            engine.tracker.regions[region.id]=region
            future = engine._submit(engine._region(region,image,bounds,'Document',engine.generation,capture_rect=bounds))
            wait(qt,lambda: future.done())
            future.result()
            qt.processEvents()
        assert len(results)==count and not errors
        assert all(preserves_values(result.source,result.arabic) for result in results)
        assert all(not any(c in result.arabic for c in '٠١٢٣٤٥٦٧٨٩') for result in results)
        if fixture=='paragraphs.png':
            assert '73' in results[0].source and '73' in results[0].arabic
            assert results[0].rect.bottom < results[1].rect.y < results[2].rect.y
        else:
            assert '$206,000,000,000' in results[-1].arabic
            assert any('15,000x' in result.arabic for result in results)
            assert any('11x' in result.arabic for result in results)
            assert sum(result.source.startswith('•') for result in results)==6
            assert len({result.rect.right for result in results[1:7]})==1
    finally:
        engine.close(); store.close()


def test_visual_anchors_scroll_clipping_changes_and_no_wraparound():
    image = cv2.imread(str(FIXTURES/'paragraphs.png'))
    frame = np.zeros((500,800,3),np.uint8)
    frame[40:40+image.shape[0],40:40+image.shape[1]]=image
    bounds=Rect(0,0,800,500); identity=(123,456,bounds)
    tracker=VisualAnchors()
    for key,box in [('first',Rect(53,60,527,40)),('second',Rect(53,132,547,64)),('third',Rect(55,228,203,16))]:
        result=Translation(key,'Source','ترجمة',box,source_window=identity)
        tracker.add(result,frame,box,30)
    assert len(tracker.items)==3
    assert tracker.update(frame,bounds)==([],[])
    scrolled=np.zeros_like(frame); scrolled[:-72]=frame[72:]
    moved,lost=tracker.update(scrolled,bounds)
    assert lost==['first']
    assert {key for key,old,new in moved}=={'second','third'}
    assert all(new.y==old.y-72 for key,old,new in moved)
    assert tracker.update(scrolled,bounds)==([],[])
    changed=scrolled.copy(); second=tracker.items['second'].rect
    changed[second.y:second.bottom,second.x:second.right]=0
    assert 'second' in tracker.update(changed,bounds)[1]


def test_overlay_tracks_source_preserving_drag_offset_and_has_outer_circle():
    qt=QApplication.instance() or QApplication([])
    settings=Settings();settings.overlay.fade_ms=0
    manager=OverlayManager(settings,lambda error:None)
    result=Translation('manual','Source','نص عربي',Rect(100,200,350,40))
    manager.show(result); qt.processEvents()
    overlay=manager.windows['manual']; overlay.move(overlay.x()+40,overlay.y()+20)
    old=overlay.pos()
    manager.follow_source('manual',Rect(100,140,350,40))
    assert overlay.x()==old.x() and overlay.y()==old.y()-60
    from arabic_lens.overlay import OverlayInteraction
    control=OverlayInteraction(overlay,lambda:None);control.follow_overlay();control.show();qt.processEvents()
    close=control.button_rects()[0]
    assert close.width()==close.height()==28
    # Hidden fixture HWNDs are not composed/moved on the physical desktop.
    corner=control.pos()+close.center()
    assert abs(corner.x()-(overlay.x()+overlay.width()))<=2
    assert abs(corner.y()-overlay.y())<=2
    control.deleteLater();manager.clear(immediate=True)


def test_manual_scroll_pipeline_reuses_translation_and_ocr(monkeypatch,tmp_path):
    qt=QApplication.instance() or QApplication([])
    source=cv2.imread(str(FIXTURES/'paragraphs.png'))
    original=np.zeros((500,800,3),np.uint8)
    original[40:40+source.shape[0],40:40+source.shape[1]]=source
    desktop=[original]
    bounds=Rect(0,0,800,500);identity=(123,456,bounds)
    class Capture:
        calls=0
        def capture(self,rect):
            self.calls+=1
            return desktop[0][rect.y:rect.bottom,rect.x:rect.right].copy()
        def close(self):pass
    class Preview(Capture):
        def capture(self,rect):
            return cv2.resize(super().capture(rect),(320,180))
    monkeypatch.setattr(engine_module,'CaptureService',Capture)
    monkeypatch.setattr(engine_module,'PreviewCaptureService',Preview)
    monkeypatch.setattr(engine_module,'source_window_current',lambda source:True)
    calls=[]
    original_recognize=engine_module.WindowsOcrProvider.recognize
    async def recognize(provider,image):
        calls.append(1);return await original_recognize(provider,image)
    monkeypatch.setattr(engine_module.WindowsOcrProvider,'recognize',recognize)
    settings=Settings(scan_ms=250);settings.overlay.fade_ms=0
    store=TranslationStore(tmp_path/'scroll.db',settings);engine=Engine(settings,store)
    manager=OverlayManager(settings,lambda error:None)
    results=[]
    statuses=[];engine.status.connect(statuses.append)
    engine.translated.connect(results.append);engine.translated.connect(manager.show)
    engine.source_moved.connect(manager.follow_source)
    engine.source_lost.connect(lambda key:manager.remove(key,immediate=True))
    try:
        engine.translate_region(bounds,'Document',identity)
        wait(qt,lambda:len(manager.windows)==3)
        second=manager.windows['manual:1'];old_y=second.y()
        wait(qt,lambda:engine.preview_capture.calls>=2)
        full_calls=engine.capture.calls
        initial_ocr_calls=len(calls)
        QTest.qWait(550);qt.processEvents()
        assert engine.capture.calls==full_calls and len(calls)==initial_ocr_calls
        scrolled=np.zeros_like(original);scrolled[:-72]=original[72:];desktop[0]=scrolled
        wait(qt,lambda:'manual' not in manager.windows and second.y()==old_y-72)
        # A changed source may receive a bounded OCR confirmation before its
        # overlay is retired. It must never issue another translation.
        assert len(results)==3 and len(calls)<=initial_ocr_calls+2
        scroll_ocr_calls=len(calls)
        QTest.qWait(350);qt.processEvents()
        assert len(calls)==scroll_ocr_calls
        desktop[0]=np.zeros_like(original)
        wait(qt,lambda:not manager.windows)
        assert len(results)==3 and len(calls)<=scroll_ocr_calls+4
    finally:
        manager.clear(immediate=True);engine.close();store.close()


@pytest.mark.parametrize('fixture,count', [('paragraphs.png',3),('financial-list.png',8)])
def test_watch_detects_documents_and_idles_without_extra_ocr(monkeypatch,tmp_path,fixture,count):
    qt=QApplication.instance() or QApplication([])
    image=cv2.imread(str(FIXTURES/fixture)); bounds=Rect(0,0,image.shape[1],image.shape[0])
    class Capture:
        calls=0
        def capture(self,rect):
            self.calls+=1
            return image[rect.y:rect.bottom,rect.x:rect.right].copy()
        def close(self):pass
    class Preview(Capture):
        def capture(self,rect):return cv2.resize(super().capture(rect),(320,180))
    monkeypatch.setattr(engine_module,'CaptureService',Capture)
    monkeypatch.setattr(engine_module,'PreviewCaptureService',Preview)
    monkeypatch.setattr(engine_module,'active_window',lambda active=True:(123,bounds,'Document'))
    monkeypatch.setattr(engine_module,'source_window_current',lambda source:True)
    settings=Settings(scan_ms=250,stability_ms=250)
    store=TranslationStore(tmp_path/'watch.db',settings);engine=Engine(settings,store)
    results=[];engine.translated.connect(results.append)
    try:
        engine.set_watch(True)
        wait(qt,lambda:len({r.source for r in results})>=count)
        sources={r.source for r in results}
        assert len(sources)==count
        if fixture=='financial-list.png':
            assert any('$206,000,000,000' in r.arabic for r in results)
        assert all(preserves_values(r.source,r.arabic) for r in results)
        captures=engine.capture.calls;result_count=len(results)
        start=time.monotonic()
        while time.monotonic()-start<.65:
            qt.processEvents();time.sleep(.01)
        assert engine.capture.calls==captures and len(results)==result_count
    finally:
        engine.close();store.close()


def test_focused_watch_area_crops_capture_and_removes_scrolled_text(monkeypatch,tmp_path):
    qt=QApplication.instance() or QApplication([])
    source=cv2.imread(str(FIXTURES/'paragraphs.png'))
    frame=np.zeros((500,800,3),np.uint8)
    frame[:source.shape[0],:source.shape[1]]=source
    desktop=[frame]; selected=Rect(0,0,600,175); full=Rect(0,0,800,500)
    class Capture:
        captured=[]
        def capture(self,rect):
            self.captured.append(rect)
            return desktop[0][rect.y:rect.bottom,rect.x:rect.right].copy()
        def close(self):pass
    class Preview(Capture):
        def capture(self,rect):return cv2.resize(super().capture(rect),(320,180))
    monkeypatch.setattr(engine_module,'CaptureService',Capture)
    monkeypatch.setattr(engine_module,'PreviewCaptureService',Preview)
    monkeypatch.setattr(engine_module,'active_window',lambda active=True:(123,full,'Document'))
    monkeypatch.setattr(engine_module,'window_identity',lambda hwnd:(123,456,full))
    monkeypatch.setattr(engine_module,'source_window_current',lambda source:True)
    settings=Settings(watch_region=list(vars(selected).values()),scan_ms=900,stability_ms=700)
    store=TranslationStore(tmp_path/'area.db',settings);engine=Engine(settings,store)
    results=[];lost=[];moved=[]
    engine.translated.connect(results.append)
    engine.source_lost.connect(lost.append)
    engine.source_moved.connect(lambda key,rect:moved.append((key,rect)))
    try:
        engine.set_watch(True)
        wait(qt,lambda:len(results)>=2)
        assert len(results)==2
        first=next(r for r in results if '73' in r.source)
        second=next(r for r in results if 'Monday' in r.source)
        assert engine.capture.captured and all(r==selected for r in engine.capture.captured)
        assert engine.preview_capture.captured and all(r==selected for r in engine.preview_capture.captured)
        scrolled=np.zeros_like(frame);scrolled[:-72]=frame[72:];desktop[0]=scrolled
        wait(qt,lambda:first.id in lost and any(key==second.id for key,rect in moved))
        assert next(rect for key,rect in moved if key==second.id).y == second.rect.y-72
        assert all(r==selected for r in engine.capture.captured)
    finally:
        engine.close();store.close()


def test_selector_finish_does_not_count_as_cancel():
    from arabic_lens.selection import SelectionManager
    from arabic_lens.localization import LocalizationService
    from arabic_lens.config import Settings
    qt=QApplication.instance() or QApplication([])
    selected=[];cancelled=[]
    manager=SelectionManager(LocalizationService(Settings()),selected.append,on_cancel=lambda:cancelled.append(1))
    manager.begin();qt.processEvents()
    region=Rect(10,20,100,50);manager.finish(region)
    assert selected==[region] and not cancelled
    manager.begin();qt.processEvents();manager.cancel()
    assert cancelled==[1]


def test_watch_area_persists_and_rejects_invalid_rectangles(tmp_path):
    from arabic_lens.config import SettingsService
    service=SettingsService(tmp_path)
    service.settings.watch_region=[-1600,40,900,620]
    service.save()
    assert SettingsService(tmp_path).settings.watch_region==[-1600,40,900,620]
    service.settings.watch_region=[0,0,-10,50]
    service.save()
    assert SettingsService(tmp_path).settings.watch_region is None


def test_compact_translation_type_stays_readable():
    from arabic_lens.overlay import ArabicSurface, OverlayInteraction
    qt=QApplication.instance() or QApplication([])
    settings=Settings()
    row=ArabicSurface(settings.overlay,'• القيمة المقدرة: $206,000,000,000')
    row.fit_to_source(Rect(0,0,224,14),max_extra=80)
    paragraph=ArabicSurface(settings.overlay,'هذا النص يشرح الحدث بشكل واضح وموجز.')
    paragraph.fit_to_source(Rect(0,0,450,40),max_extra=80)
    assert 16 <= row.document.defaultFont().pixelSize() <= paragraph.document.defaultFont().pixelSize() <= 23
    assert paragraph.document.defaultFont().pixelSize()-row.document.defaultFont().pixelSize() <= 7
    larger=Settings().overlay
    larger.font_size=40
    custom=ArabicSurface(larger,'A short translated line')
    custom.fit_to_source(Rect(0,0,500,90))
    assert custom.document.defaultFont().pixelSize()>paragraph.document.defaultFont().pixelSize()
    control=OverlayInteraction(row,lambda:None)
    control.follow_overlay()
    close,*other=control.button_rects()
    assert close.width()==28 and all(button.width()==24 for button in other)
    control.deleteLater();row.deleteLater();paragraph.deleteLater();custom.deleteLater()


def test_select_watch_area_wires_selection_to_persistent_fast_watch(monkeypatch):
    from types import SimpleNamespace
    from arabic_lens.app import Application
    import arabic_lens.app as app_module
    qt=QApplication.instance() or QApplication([])
    app=Application.__new__(Application)
    app.settings=Settings();app.capture_request=0;app.paused=False;app.closing=False
    app.selection_purpose='quick';app.selection_restore_watch=False
    app.preset_dialog=None
    app.window=SimpleNamespace(hide=lambda:None,rebuild=lambda page:None)
    app.overlays=SimpleNamespace(clear=lambda **kwargs:None)
    app.source_monitor=SimpleNamespace(clear=lambda:None)
    saved=[];app.service=SimpleNamespace(save=lambda:saved.append(1))
    modes=[]
    class Engine:
        watch=True
        def set_watch(self,enabled):
            self.watch=enabled;modes.append(enabled)
    app.engine=Engine()
    begun=[]
    app.selector=SimpleNamespace(windows=[],begin_multi=lambda *args:begun.append(args))
    monkeypatch.setattr(app_module,'active_window',lambda:(123,Rect(0,0,800,500),'Game'))
    monkeypatch.setattr(app_module,'window_identity',lambda hwnd:(hwnd,456,Rect(0,0,800,500)))
    monkeypatch.setattr(app_module,'restore_capture_focus',lambda identity:True)
    monkeypatch.setattr(app_module,'window_at_rect',lambda rect:(123,456,Rect(0,0,800,500)))
    monkeypatch.setattr(app_module,'focus_chosen_window',lambda hwnd:True)
    Application.action(app,'select_watch_area')
    wait(qt,lambda:bool(begun),seconds=2)
    assert modes==[False] and app.selection_window[0]==123
    Application.watch_areas_selected(app,[Rect(40,50,360,180),Rect(410,50,200,180)])
    wait(qt,lambda:len(modes)==2,seconds=2)
    assert app.settings.watch_areas==[[40,50,360,180],[410,50,200,180]]
    assert app.settings.watch_previous==app.settings.watch_areas
    assert app.settings.watch_region is None
    assert modes==[False,True] and saved


def test_translator_result_contains_only_the_requested_translation():
    from types import SimpleNamespace
    from arabic_lens.app import Application
    from arabic_lens.localization import LocalizationService
    app=Application.__new__(Application)
    app.settings=Settings()
    app.l=LocalizationService(app.settings)
    shown=[];states=[];foot=[]
    app.window=SimpleNamespace(translation_feedback=SimpleNamespace(setText=shown.append),
        status_label=SimpleNamespace(setText=foot.append))
    app.report=states.append
    Application.tested(app,True,'هذه هي الترجمة.')
    assert shown==['هذه هي الترجمة.']
    assert states and foot
