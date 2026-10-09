"""Install the reviewed Dressmaker phrase pack in the normal or a test cache."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arabic_lens.config import SettingsService
from arabic_lens.storage import TranslationStore

parser = argparse.ArgumentParser()
parser.add_argument('--data-dir')
parser.add_argument('--reload', action='store_true', help='Explicitly reload a cleared pack')
args = parser.parse_args()
service = SettingsService(args.data_dir)
store = TranslationStore(service.directory / 'translations.db', service.settings)
count = store.seed_pack(Path(__file__).resolve().parents[1] / 'arabic_lens/data/dressmaker.json', args.reload)
store.close()
print(f'Added {count} reviewed cache keys to {service.directory / "translations.db"}')
