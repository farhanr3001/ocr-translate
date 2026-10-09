import asyncio
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from arabic_lens.config import Settings, SettingsService
from arabic_lens.models import Rect, TextBlock, Translation
from arabic_lens.ocr import OcrService, WindowsOcrProvider
from arabic_lens.text import TextFilterService
from arabic_lens.translation import TranslationService, TranslationError
from arabic_lens.offline import OfflineTranslationProvider
from arabic_lens.storage import TranslationStore
from arabic_lens.engine import whole_screen_tiles
from arabic_lens.localization import LocalizationService
from arabic_lens.ui import SettingsWindow
from arabic_lens.progress import TranslationProgress


def test_multiline_headlines_stay_in_their_column_and_label_expansion_is_bounded():
    from arabic_lens.overlay import ArabicSurface
    from arabic_lens.config import OverlaySettings
    QApplication.instance() or QApplication([])
    paragraph=ArabicSurface(OverlaySettings(),'هذا وصف طويل يتكون من عدة كلمات لعنوان خبر داخل عمود جانبي ضيق')
    paragraph.fit_to_source(Rect(0,0,240,34),max_extra=80)
    assert paragraph.width()<=256
    label=ArabicSurface(OverlaySettings(),'اسم طويل يحتاج إلى مساحة إضافية للقراءة')
    label.fit_to_source(Rect(0,0,80,18),max_extra=80)
    assert label.width()<=160
    paragraph.deleteLater();label.deleteLater()


def test_second_scale_can_complete_partial_line_without_duplicate():
    from arabic_lens.ocr import merge_recognized_line
    lines=[TextBlock('You need to find',Rect(20,20,140,20))]
    assert merge_recognized_line(lines,TextBlock('You need to find the key.',Rect(20,20,250,20)))
    assert len(lines)==1 and lines[0].text.endswith('the key.')
    assert not merge_recognized_line(lines,TextBlock('the key.',Rect(180,20,90,20)))
    label=[TextBlock('Flowers',Rect(0,0,80,20),standalone=True)]
    assert not merge_recognized_line(label,TextBlock('Flowers e',Rect(0,0,100,20)))


def test_fullscreen_overlap_prefers_complete_paragraph_without_touching_other_zone():
    from arabic_lens.engine import reconcile_zone_blocks
    from arabic_lens.anchors import VisualAnchors
    events=[]
    state={'bounds':Rect(500,0,900,900),'blocks':{},'tracker':SimpleNamespace(regions={})}
    other={'bounds':Rect(0,0,1024,900),'namespace':'0-',
           'blocks':{'1':TextBlock('runners',Rect(661,761,52,8)),'2':TextBlock('Home',Rect(388,200,50,20))},
           'tracker':SimpleNamespace(regions={'1':object(),'2':object()})}
    fake=SimpleNamespace(zone_states={0:other,1:state},jobs={},anchors=VisualAnchors(),removed=SimpleNamespace(emit=events.append))
    full=TextBlock('The driver does not concern themselves with speed runners',Rect(160,738,480,32))
    assert reconcile_zone_blocks(fake,state,state['bounds'],[full])==[full]
    assert events==['watch-0-1'] and list(other['blocks'])==['2']


def test_short_lowercase_continuation_remains_in_its_paragraph():
    from arabic_lens.text import group_lines
    blocks=group_lines([TextBlock('The driver does not concern themselves with speed',Rect(0,0,400,14)),
                        TextBlock('runners',Rect(0,23,52,8),standalone=True)])
    assert len(blocks)==1 and blocks[0].text.endswith('speed runners')


def test_ignore_matches_whole_group_not_wrapped_line_or_substring():
    settings = Settings(ignored=['Continue','Exit'])
    service = OcrService(None,TextFilterService(settings))
    lines = [TextBlock('Continue',Rect(0,0,100,20),standalone=True),
             TextBlock('through the tunnel until you reach the village.',Rect(0,24,440,20))]
    blocks = service._group(lines,False)
    assert len(blocks) == 1
    assert not service.text_filter.reason(blocks[0])
    assert service.text_filter.is_ui_label('  CONTINUE!!! ')
    assert not service.text_filter.is_ui_label('Exit game')
    assert not service.text_filter.is_ui_label('Please continue')
    assert service.text_filter.reason(TextBlock('211K',Rect(0,0,30,10)))=='numeric value'
    assert service.text_filter.reason(TextBlock('Q',Rect(0,0,20,20)))=='single glyph / icon'


def test_watch_second_pass_recovers_missing_label():
    class Provider:
        calls = 0
        async def recognize(self,image):
            self.calls += 1
            if self.calls == 1:
                return [TextBlock('The paragraph is visible.',Rect(10,10,250,20))]
            return [TextBlock('The paragraph is visible.',Rect(20,20,500,40)),
                    TextBlock('Notifications',Rect(20,160,160,40),standalone=True)]
    service = OcrService(Provider(),TextFilterService(Settings()))
    result = asyncio.run(service.read(np.zeros((150,400,3),np.uint8)))
    assert {b.text for b in result} == {'The paragraph is visible.','Notifications'}


@pytest.mark.parametrize('mode',['selection','fullscreen'])
def test_clean_desktop_navigation_paragraphs_tabs_and_headlines(mode):
    fixture=Path(__file__).resolve().parents[1]/'artifacts/desktop-clean-coverage/source.png'
    if not fixture.exists(): pytest.skip('User screenshot is a local fixture')
    image=cv2.imread(str(fixture)); h,w=image.shape[:2]
    async def read():
        service=OcrService(WindowsOcrProvider(),TextFilterService(Settings()))
        if mode=='selection': return await service.read(image,manual=True)
        blocks=[]
        for core,bounds,_ in whole_screen_tiles(Rect(0,0,w,h),(180,320)):
            for b in await service.read(image[bounds.y:bounds.bottom,bounds.x:bounds.right]):
                r=b.rect;b.rect=Rect(r.x+bounds.x,r.y+bounds.y,r.w,r.h)
                if core.x <= b.rect.x+r.w//2 < core.right and core.y <= b.rect.y+r.h//2 < core.bottom:
                    blocks.append(b)
        return blocks
    blocks=asyncio.run(read())
    texts=[b.text.casefold() for b in blocks]
    nav=['Home','Explore','Notifications','Chat','Grok','History','Creator Studio','Premium','Profile','More']
    for label in nav:
        assert any(b.text.casefold()==label.casefold() and 370<b.rect.x<410 for b in blocks),label
    for phrase in ['For you','Following','SPEED GANG','omiefans','OVO SOUND','I know Reggie',
                   'Shit is starting','The Los Santos','And people','Live on X',"Today's News",
                   'MARKET OPEN','No Pixel 5','LGBTQ','Bitcoin crypto',
                   "Asmongold's",'Pelican Lounges','Georgia Sgt.']:
        assert any(phrase.casefold() in text for text in texts),phrase
    long_post=next(b for b in blocks if b.text.startswith('And people'))
    assert 'Rockstar' in long_post.text and 'system' in long_post.text
    assert not long_post.standalone


def test_translation_parallelism_dedup_failure_and_lock_cleanup(tmp_path):
    async def scenario():
        class Provider:
            calls=[]; active=0; peak=0
            async def translate(self,text):
                self.calls.append(text);self.active+=1;self.peak=max(self.peak,self.active)
                await asyncio.sleep(.01);self.active-=1
                if text=='Broken':raise TranslationError('translation_failed')
                return 'ترجمة'
        provider=Provider();store=TranslationStore(tmp_path/'cache.db',Settings())
        service=TranslationService(provider,store)
        results=await asyncio.gather(*(service.translate(t) for t in ['Home','Home','Explore','Broken']),return_exceptions=True)
        assert provider.calls.count('Home')==1 and provider.peak>1
        assert results[0][0]=='ترجمة' and results[1][1]
        assert isinstance(results[-1],TranslationError) and not service.locks
        store.close()
    asyncio.run(scenario())


def test_identifiers_and_known_technical_labels_finish_without_model_retry(tmp_path):
    class Provider:
        async def translate(self,text):raise AssertionError('No inference required')
    async def scenario():
        store=TranslationStore(tmp_path/'cache.db',Settings())
        service=TranslationService(Provider(),store)
        assert (await service.translate('@drahirt'))[0]=='@drahirt'
        assert (await service.translate('NFL'))[0]=='دوري NFL'
        assert (await service.translate('ENG'))[0]=='الإنجليزية'
        store.close()
    asyncio.run(scenario())


def test_cpu_batch_excludes_cancelled_requests_and_keeps_live_ones():
    async def scenario():
        p=OfflineTranslationProvider();seen=[]
        def batch(entries):
            seen.extend(t for t,_,_ in entries)
            return ['ترجمة' for _ in entries]
        p._batch=batch
        first=asyncio.create_task(p.translate('Old source'))
        second=asyncio.create_task(p.translate('Visible source'))
        await asyncio.sleep(0);first.cancel()
        await asyncio.gather(first,return_exceptions=True)
        assert await second=='ترجمة'
        assert seen==['Visible source']
        await p.close()
    asyncio.run(scenario())


def test_ignore_table_bilingual_search_edit_storage_and_toggle(tmp_path):
    qt=QApplication.instance() or QApplication([])
    service=SettingsService(tmp_path);settings=service.settings
    settings.ignored+=['Custom label'];settings.ignored_translations={'Custom label':'نص مخصص'}
    store=TranslationStore(tmp_path/'cache.db',settings)
    window=SettingsWindow(settings,LocalizationService(settings),store)
    try:
        table=window.ignore_list
        assert table.headerItem().text(0)=='English' and table.headerItem().text(1)=='Arabic'
        window.search_ignore('خروج')
        assert not table.topLevelItem(0).isHidden()
        window.search_ignore('مخصص')
        assert table.topLevelItem(0).isHidden() and not table.topLevelItem(table.topLevelItemCount()-1).isHidden()
        values=[];window.apply_requested.connect(values.append)
        window.fields['show_translation_boxes'].setChecked(True);window.apply()
        assert values[0]['show_translation_boxes'] and values[0]['ignored_translations']['Custom label']=='نص مخصص'
        settings.show_translation_boxes=True;service.save()
        assert SettingsService(tmp_path).settings.show_translation_boxes
    finally:
        window.hide();window.deleteLater();qt.processEvents();store.close()


def test_progress_sources_moves_zone_removal_and_no_timer_expiry(monkeypatch):
    qt=QApplication.instance() or QApplication([])
    settings=Settings(show_translation_boxes=True)
    progress=TranslationProgress(settings,LocalizationService(settings))
    source=(1,2,Rect(0,0,800,600))
    try:
        for key in ('watch-0-1','watch-1-1','manual'):
            progress.update({'id':key,'rect':Rect(20,20,80,20),'percent':25,'stage':'Detected','source_window':source})
        progress.complete(Translation('watch-0-1','Home','الرئيسية',Rect(20,20,80,20),source_window=source))
        progress.remove('watch-1-1')
        assert set(progress.entries)=={'watch-0-1','manual'}
        progress.move('manual',Rect(20,80,80,20))
        assert progress.entries['manual']['rect'].y==80
        monkeypatch.setattr('arabic_lens.progress.source_window_current',lambda source:True)
        progress.check_sources()
        assert progress.entries['watch-0-1']['percent']==100
        monkeypatch.setattr('arabic_lens.progress.source_window_current',lambda source:False)
        progress.check_sources();assert not progress.entries
    finally:progress.clear()
