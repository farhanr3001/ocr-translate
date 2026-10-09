"""Add manually reviewed text visible in official screenshot/trailer fixtures."""
import json
from pathlib import Path
from arabic_lens.text import normalize

path = Path('arabic_lens/data/dressmaker.json')
pack = json.loads(path.read_text(encoding='utf-8'))
# No generated completion of clipped item names, fuzzy aliases or invented prices.
rows = '''Prudence|برودنس|steam-00.jpg
Environment (1/9)|البيئة (1/9)|steam-01.jpg
Light|الإضاءة|steam-01.jpg
Light Colour (1/6)|لون الإضاءة (1/6)|steam-01.jpg
Viewfinder: Off|معاينة الإطار: متوقفة|steam-01.jpg
Take Photo|التقاط صورة|steam-01.jpg
Photo|صورة|steam-01.jpg
Black and Grey|أسود ورمادي|steam-02.jpg
Midnight Black|أسود ليلي|steam-02.jpg
Midnight Black V...|أسود ليلي…|steam-02.jpg
Glacier Blue Silk|حرير أزرق جليدي|steam-02.jpg
Aquamarine Blue...|أزرق زبرجدي…|steam-02.jpg
Floral Silk Broca...|حرير مزخرف بالورود…|steam-02.jpg
Blue Dainty Cont...|أزرق رقيق…|steam-02.jpg
Teal Blue Velvet|مخمل أزرق مخضر|steam-02.jpg
Diamond Filigree...|زخرفة ماسية…|steam-02.jpg
Peacock Crushed...|قماش بلون الطاووس…|steam-02.jpg
Steel Blue Cotto...|قطن أزرق فولاذي…|steam-02.jpg
Burlap|خيش|steam-02.jpg
Paisley Emerald|نقشة بيزلي زمردية|steam-02.jpg
The International Emporium|المتجر العالمي|steam-03.jpg
Emporium|متجر|steam-03.jpg
Formal|رسمي|steam-03.jpg
Professional|مهني|steam-03.jpg
Fabrics|أقمشة|steam-03.jpg
Silk|حرير|steam-03.jpg
Pink|وردي|steam-03.jpg
Glamour|جاذبية|steam-03.jpg
Eveningwear|ملابس سهرة|steam-03.jpg
metres|أمتار|steam-03.jpg
Charcoal Grey Co...|رمادي فحمي…|steam-03.jpg
Cool Grey Linen|كتان رمادي بارد|steam-03.jpg
Barbara Pink Silk|حرير باربرا الوردي|steam-03.jpg
Cool Blush Silk|حرير وردي بارد|steam-03.jpg
Champagne Whit...|أبيض شامبانيا…|steam-03.jpg
Paisley Plum Silk...|حرير بيزلي بلون البرقوق…|steam-03.jpg
Grain Quality: 100%|جودة اتجاه النسيج: 100%|steam-04.jpg
Cotton|قطن|steam-04.jpg
Patterns|أنماط القص|steam-04.jpg
Space|مسافة|steam-06.jpg
Photo Preview|معاينة الصورة|steam-07.jpg
Environment (1/6)|البيئة (1/6)|steam-07.jpg
Light Colour (2/6)|لون الإضاءة (2/6)|steam-07.jpg
Viewfinder: On|معاينة الإطار: مفعلة|steam-07.jpg
Sewing Complete!|اكتملت الخياطة!|trailer/frame-003.jpg
Zoom out/orbit (hold)|تصغير أو تدوير العرض (اضغط مطولًا)|trailer/frame-003.jpg
Pan Camera|تحريك الكاميرا|trailer/frame-003.jpg
Camera|الكاميرا|trailer/frame-003.jpg
Zoom|تكبير العرض|trailer/frame-003.jpg
Add Point|إضافة نقطة|trailer/frame-004.jpg
Place|وضع|trailer/frame-004.jpg
Finish|إنهاء|trailer/frame-004.jpg
Photo Mode|وضع التصوير|trailer/frame-020.jpg
Light Colour (4/6)|لون الإضاءة (4/6)|trailer/frame-020.jpg
Avoid: Black|تجنب اللون الأسود|trailer/frame-021.jpg
Off rack dress (RepeatingQuest)|فستان جاهز (طلب متكرر)|trailer/frame-025.jpg
Eclectic|متنوع الأساليب|trailer/frame-025.jpg
Shimmering|لامع|trailer/frame-025.jpg
Uncomfortable|غير مريح|trailer/frame-025.jpg
Black Cotton|قطن أسود|trailer/frame-026.jpg
Mica Sequin|ترتر ميكا|trailer/frame-033.jpg
Mica Sequin (10.0m)|ترتر ميكا (10.0m)|trailer/frame-033.jpg
This will not do.|هذا غير مقبول.|trailer/frame-047.jpg
Materials|المواد|trailer/frame-051.jpg
Labour|أجرة العمل|trailer/frame-051.jpg
Quality Bonus (%)|مكافأة الجودة (%)|trailer/frame-051.jpg
Prestige Bonus (%)|مكافأة المكانة (%)|trailer/frame-051.jpg
Sell Price|سعر البيع|trailer/frame-051.jpg
Sell|بيع|trailer/frame-051.jpg
Apprentice|متدرب|trailer/frame-051.jpg
Novice|مبتدئ|trailer/frame-051.jpg
Environment (4/12)|البيئة (4/12)|trailer/frame-051.jpg
Light Colour (1/9)|لون الإضاءة (1/9)|trailer/frame-051.jpg
Out now|متاحة الآن|trailer/frame-058.jpg
On Steam|على ستيم|trailer/frame-060.jpg'''
seen = {normalize(e['english']) for e in pack['entries']}
added = 0
for row in rows.splitlines():
    english, arabic, evidence = row.split('|')
    if normalize(english) not in seen:
        assert (Path('artifacts/dressmaker') / evidence).is_file()
        pack['entries'].append(dict(english=english, arabic=arabic, evidence=evidence))
        seen.add(normalize(english))
        added += 1
pack['id'] = 'dressmaker-steam-4019220-v9'
pack['reviewed_fixture_count'] = 70
path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Added', added, 'reviewed entries; total', len(pack['entries']))
