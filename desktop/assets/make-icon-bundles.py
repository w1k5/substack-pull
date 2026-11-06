"""Pack resized PNG artwork as macOS ICNS and Windows ICO files."""

from pathlib import Path
import struct
import sys


def build_icns(paths: list[Path], output: Path) -> None:
    kinds = {16: b"icp4", 32: b"icp5", 64: b"icp6", 128: b"ic07",
             256: b"ic08", 512: b"ic09", 1024: b"ic10"}
    parts = []
    for path in paths:
        size = int(path.stem.split("-")[-1])
        image = path.read_bytes()
        parts.append(kinds[size] + struct.pack(">I", len(image) + 8) + image)
    output.write_bytes(b"icns" + struct.pack(">I", 8 + sum(map(len, parts))) + b"".join(parts))


def build_ico(paths: list[Path], output: Path) -> None:
    selected = [(int(path.stem.split("-")[-1]), path.read_bytes()) for path in paths
                if int(path.stem.split("-")[-1]) <= 256]
    offset = 6 + len(selected) * 16
    with output.open("wb") as handle:
        handle.write(struct.pack("<HHH", 0, 1, len(selected)))
        for size, image in selected:
            handle.write(struct.pack("<BBBBHHII", size % 256, size % 256,
                                     0, 0, 1, 32, len(image), offset))
            offset += len(image)
        for _, image in selected:
            handle.write(image)


if __name__ == "__main__":
    images = [Path(value) for value in sys.argv[3:]]
    build_icns(images, Path(sys.argv[1]))
    build_ico(images, Path(sys.argv[2]))
