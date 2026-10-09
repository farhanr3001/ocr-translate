import argparse
import sys


def main():
    if sys.platform != "win32":
        raise SystemExit("Arabic Lens requires Windows 10 version 2004 or later.")
    from arabic_lens.windows import enable_dpi
    enable_dpi()
    parser = argparse.ArgumentParser(description="Arabic Lens screen translator")
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--data-dir")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    from arabic_lens.app import run
    return run(args.data_dir, args.minimized, args.smoke_test)


if __name__ == "__main__":
    if '--smoke-test' in sys.argv:
        # Automated startup checks must not open a PyInstaller exception dialog
        # on the player's desktop, even when packaging itself is broken.
        try:
            raise SystemExit(main())
        except Exception:
            import traceback
            from pathlib import Path
            index = sys.argv.index('--data-dir') if '--data-dir' in sys.argv else None
            directory = Path(sys.argv[index + 1]) if index is not None else Path('artifacts')
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'startup-error.log').write_text(traceback.format_exc(), encoding='utf-8')
            raise SystemExit(1)
    else:
        raise SystemExit(main())
