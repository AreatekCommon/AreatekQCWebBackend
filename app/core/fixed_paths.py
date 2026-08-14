from __future__ import annotations

from pathlib import Path

KUKA_TRAJECTORIES_DIR = Path(r"C:\Users\Areatek\Desktop\KUKA TRAJECTORIES")
PARSED_TRAJECTORIES_DIR = Path(r"C:\Users\Areatek\Desktop\AreatekQC\Server\data\Trajectories")
MARKERS_DIR = Path(r"C:\Users\Areatek\Desktop\AreatekQC\Server\data\Markers")


def is_under_directory(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
