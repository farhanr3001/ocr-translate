"""Reviewed reference translations; matching always uses the English column."""
DEFAULT_ARABIC = dict(zip(
    ['Exit', 'Exit Game', 'Quit', 'Quit Game', 'Close', 'Cancel', 'Back', 'Continue',
     'Restart', 'Resume', 'Leave', 'Start', 'Play', 'Pause', 'Settings', 'Options',
     'Apply', 'Confirm', 'Yes', 'No', 'OK', 'Save', 'Load', 'Menu', 'Skip'],
    ['خروج', 'الخروج من اللعبة', 'خروج', 'الخروج من اللعبة', 'إغلاق', 'إلغاء', 'رجوع', 'متابعة',
     'إعادة التشغيل', 'استئناف', 'مغادرة', 'بدء', 'لعب', 'إيقاف مؤقت', 'الإعدادات', 'الخيارات',
     'تطبيق', 'تأكيد', 'نعم', 'لا', 'موافق', 'حفظ', 'تحميل', 'القائمة', 'تخطي']))


def reference_translation(english, custom, store):
    from .text import label_key
    key = label_key(english)
    for source in (custom, DEFAULT_ARABIC):
        for word, arabic in source.items():
            if label_key(word) == key:
                return arabic
    return store.get(english) or ''
