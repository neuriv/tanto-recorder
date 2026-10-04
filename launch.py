# Select packaged or sibling read-only Engine code before starting the action capture worker.
# PyInstaller exposes bundled files through _MEIPASS; source development uses this checkout.
# Keep product data/state paths separate from shared implementation; see CODE_GUIDE.md.
import os
from pathlib import Path
import sys

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
os.environ['TANTO_PRODUCT_ROOT']=str(ROOT)
default_engine=ROOT.parent/'tanto'
if not default_engine.is_dir(): default_engine=ROOT.parent/'tanto-engine'
engine=Path(os.environ.get('TANTO_ENGINE_ROOT',default_engine))
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'runtime' if (ROOT/'runtime').exists() else engine/'runtime')]
from action_capture import main

if __name__=='__main__': raise SystemExit(main())
