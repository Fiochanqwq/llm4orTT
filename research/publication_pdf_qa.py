"""Inspect Chinese PDF structure and render every page for visual review."""
import argparse
import json
import subprocess
from pathlib import Path
from pypdf import PdfReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pdftoppm", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    pdf = out / "研究报告.pdf"
    reader = PdfReader(pdf)
    texts = [page.extract_text() for page in reader.pages]
    if len(texts) < 9 or any(len(text.strip()) < 100 for text in texts):
        raise ValueError("Unexpected page count or nearly empty overflow page")
    combined = "".join(texts)
    for phrase in ("可靠性先于漂亮分数", "2,880", "360", "1,355", "141,969", "未完成"):
        if phrase not in combined:
            raise ValueError("Missing expected Chinese content: " + phrase)
    image_directory = out / "pdf-review"
    image_directory.mkdir(exist_ok=True)
    subprocess.run([str(args.pdftoppm), "-r", "100", "-png", str(pdf),
                    str(image_directory / "page")], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    images = sorted(image_directory.glob("page-*.png"))
    if len(images) != len(texts):
        raise ValueError("Page image inventory differs from PDF")
    result = {
        "structuralChecksPassed": True, "pages": len(texts),
        "pageTextLengths": [len(text) for text in texts], "renderedPages": len(images),
        "visualReview": "Rendered page images require inspection; structural checks alone do not prove visual quality.",
    }
    (out / "pdf-qa.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
