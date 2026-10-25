import sys
from pathlib import Path

# 让测试能以包形式导入插件（from astrbot_plugin_pet_platform.pet_auth import ...）。
# 插件运行时由 AstrBot 以 data.plugins.<目录>.main 加载，不依赖这个 conftest。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
