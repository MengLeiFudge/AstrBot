from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SOURCE_ROOT = REPO_ROOT / "data" / "plugins"


def main() -> int:
    if str(PLUGIN_SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(PLUGIN_SOURCE_ROOT))

    from astrbot_plugin_qqbot_features.meme_manager.local_index import migrate_mlj_pack_index

    if len(sys.argv) <= 1:
        print("usage: migrate-meme-pack-to-manager.py <external-mlj-pack-index.json>", file=sys.stderr)
        return 2

    source_index = Path(sys.argv[1])
    result = migrate_mlj_pack_index(source_index)
    print(f"source_index={source_index}")
    print(f"copied={result['copied']}")
    print(f"updated={result['updated']}")
    print(f"skipped_missing={result['skipped_missing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
