"""Resize Pandoc code paragraphs in rendered PowerPoints.

Quarto post-render: python fix_pptx_code.py (output paths from Quarto)
Manual: python fix_pptx_code.py input.pptx [output.pptx]
Without an output argument, update the generated file in place.
"""

import os
import sys
import tempfile
import re
import zipfile
from lxml import etree
import textwrap
from pathlib import Path

# Adjust these to suit the AAIC reference template.
CODE_FONT = "Consolas"
MAX_CODE_SIZE = 18
MIN_CODE_SIZE = 12
BODY_SIZE = 20
BODY_SPACE_BEFORE = 9
CODE_FONTS = {"courier", "courier new", "consolas", "liberation mono",
              "dejavu sans mono", "cascadia mono", "monospace"}


NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def font_name(properties):
    if properties is None:
        return ""
    latin = properties.find("a:latin", NS)
    return latin.get("typeface", "") if latin is not None else ""


def font_size(properties, default):
    value = properties.get("sz") if properties is not None else None
    return int(value) / 100 if value else default


def is_code(p):
    """A code block is normally a paragraph of entirely monospaced runs."""
    runs = [r for r in p.runs if r.text.strip()]
    default = font_name(p._p.find("a:pPr/a:defRPr", NS))
    return bool(runs) and all(
        (font_name(r._r.find("a:rPr", NS)) or default).lower() in CODE_FONTS
        for r in runs
    )


def lines(text):
    # Pandoc uses vertical tabs for line breaks inside a code paragraph.
    return [line.expandtabs(4) for line in text.replace("\v", "\n").split("\n")]


def line_count(text, width, size, char_ratio, wrap=True):
    # Conservative width estimate in points; not a PowerPoint layout engine.
    capacity = max(1, int(width / (size * char_ratio)))
    count = 0
    for line in lines(text):
        if not wrap and len(line) > capacity:
            return float("inf")
        count += max(1, len(textwrap.wrap(
            line, width=capacity, break_long_words=True,
            break_on_hyphens=False, replace_whitespace=False,
        ))) if wrap else 1
    return count


def choose_size(frame, code_flags, width, height):
    # Reserve space for instructions, bullets, and printed output sharing
    # the same text box. Use the template's body defaults when absent.
    remaining = height
    paragraphs = list(frame.paragraphs)
    for p, code in zip(paragraphs, code_flags):
        if code:
            continue
        default = font_size(p._p.find("a:pPr/a:defRPr", NS), BODY_SIZE)
        size = max((font_size(r._r.find("a:rPr", NS), default)
                    for r in p.runs), default=default)
        before = p.space_before.pt if p.space_before is not None else BODY_SPACE_BEFORE
        after = p.space_after.pt if p.space_after is not None else 0
        spacing = p.line_spacing
        if hasattr(spacing, "pt"):
            line_height = spacing.pt
        else:
            line_height = size * 1.25 * (spacing if spacing is not None else 1)
        # Reserve a little horizontal space for list indentation.
        properties = p._p.find("a:pPr", NS)
        level = int(properties.get("lvl", "0")) if properties is not None else 0
        normal_width = max(1, width - 18 * level)
        remaining -= before + after + line_height * line_count(
            p.text, normal_width, size, 0.60)

    # Prefer intact code lines. Permit wrapping if no allowed size fits
    # without it. All code paragraphs in this box use the same size.
    for wrap in (False, True):
        for size in range(MAX_CODE_SIZE, MIN_CODE_SIZE - 1, -1):
            needed = sum(
                line_count(p.text, width, size, 0.65, wrap) * size * 1.20
                for p, code in zip(paragraphs, code_flags) if code
            )
            if needed <= remaining:
                return size, True
    return MIN_CODE_SIZE, False


def repair_slide_index(input_file, repaired_file):
    """Repair a missing/empty slide list using Pandoc's numbered slide relations.

    Leave a valid slide list alone, including its existing order. Refuse to
    guess if the package contains unexpected or inconsistent slide targets.
    """
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pres_name = "ppt/presentation.xml"
    rels_name = "ppt/_rels/presentation.xml.rels"
    with zipfile.ZipFile(input_file) as original:
        root = etree.fromstring(original.read(pres_name))
        slide_list = root.find(f"{{{p}}}sldIdLst")
        if slide_list is not None and len(slide_list):
            return False

        rels = etree.fromstring(original.read(rels_name))
        slides = []
        for rel in rels:
            if rel.get("Type") != r + "/slide":
                continue
            target = rel.get("Target", "")
            match = re.fullmatch(r"(?:/ppt/)?slides/slide(\d+)\.xml", target)
            if not match or rel.get("TargetMode") == "External":
                raise ValueError(f"Unexpected slide relationship: {target}")
            member = target.lstrip("/") if target.startswith("/") else "ppt/" + target
            if member not in original.namelist() or not rel.get("Id"):
                raise ValueError(f"Invalid slide relationship: {target}")
            slides.append((int(match.group(1)), rel.get("Id")))

        if not slides:
            raise ValueError(f"No registered slide relationships found in {input_file}")
        slides.sort()
        if (len({n for n, _ in slides}) != len(slides)
                or len({rid for _, rid in slides}) != len(slides)):
            raise ValueError("Duplicate slide numbers or relationship IDs")
        members = {int(m.group(1)) for name in original.namelist()
                   if (m := re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name))}
        if members != {n for n, _ in slides}:
            raise ValueError("Slide files and relationships do not match; cannot safely repair")

        if slide_list is None:
            slide_list = etree.Element(f"{{{p}}}sldIdLst")
            # OOXML order: master lists, then slide list, then size and other settings.
            preceding = {f"{{{p}}}{tag}" for tag in
                         ("sldMasterIdLst", "notesMasterIdLst", "handoutMasterIdLst")}
            index = 0
            while index < len(root) and root[index].tag in preceding:
                index += 1
            root.insert(index, slide_list)
        for i, (_, rid) in enumerate(slides, 256):
            child = etree.SubElement(slide_list, f"{{{p}}}sldId")
            child.set("id", str(i))
            child.set(f"{{{r}}}id", rid)

        with zipfile.ZipFile(repaired_file, "w") as fixed:
            for member in original.infolist():
                data = (etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                        if member.filename == pres_name else original.read(member))
                fixed.writestr(member, data)
        print(f"[pptx-code] Repaired missing/empty slide index: {len(slides)} slides")
    return True


def fix_pptx(input_file, output_file):
    """Repair before opening with python-pptx; write final output atomically."""
    print(f"[pptx-code] Processing: {input_file}")
    with tempfile.TemporaryDirectory() as temp:
        repaired = Path(temp) / "repaired.pptx"
        if repair_slide_index(input_file, repaired):
            resize_code(repaired, output_file)
        else:
            resize_code(input_file, output_file)


def resize_code(input_file, output_file):
    from pptx import Presentation
    from pptx.util import Pt
    from pptx.enum.text import MSO_AUTO_SIZE

    prs = Presentation(str(input_file))
    print(f"[pptx-code] Found {len(prs.slides)} slides")
    if not len(prs.slides):
        raise ValueError("PowerPoint has no readable slides")
    changed = 0
    changed_slides = {}
    for slide_number, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            tf = shape.text_frame
            flags = [is_code(p) for p in tf.paragraphs]
            if not any(flags):
                continue

            # Use the space inside the existing placeholder and slide.
            width = (min(shape.width, prs.slide_width - shape.left)
                     - tf.margin_left - tf.margin_right) / 12700 - 6
            height = (min(shape.height, prs.slide_height - shape.top)
                      - tf.margin_top - tf.margin_bottom) / 12700 - 6
            if width <= 0 or height <= 0:
                print(f"WARNING: slide {slide_number}: no usable space for {shape.name}")
                continue

            size, fits = choose_size(tf, flags, width, height)
            for p, code in zip(tf.paragraphs, flags):
                if not code:
                    continue
                p.space_before = Pt(0)
                p.space_after = Pt(0)
                p.line_spacing = Pt(size * 1.20)
                p.font.name = CODE_FONT
                p.font.size = Pt(size)
                for run in p.runs:
                    run.font.name = CODE_FONT
                    run.font.size = Pt(size)

            tf.word_wrap = True
            # Avoid PowerPoint shrinking the entire box, including prose,
            # or reducing code below MIN_CODE_SIZE after our calculation.
            tf.auto_size = MSO_AUTO_SIZE.NONE
            changed += sum(flags)
            changed_slides[str(slide.part.partname).lstrip("/")] = slide.part
            print(f"  slide {slide_number}: code -> {size} pt")
            if not fits:
                print(f"  WARNING: slide {slide_number}: code may overflow at "
                      f"{MIN_CODE_SIZE} pt; split the slide or shorten lines.")

    # Save atomically so an interrupted write won't destroy the original.
    if changed or input_file != output_file:
        fd, name = tempfile.mkstemp(suffix=".pptx", dir=output_file.parent)
        os.close(fd)
        try:
            # Only replace modified slide XML. Keep every other original
            # package member, including theme files and relationships.
            with zipfile.ZipFile(input_file) as original:
                with zipfile.ZipFile(name, "w") as fixed:
                    for member in original.infolist():
                        part = changed_slides.get(member.filename)
                        data = part.blob if part is not None else original.read(member)
                        fixed.writestr(member, data)
            os.replace(name, output_file)
        finally:
            Path(name).unlink(missing_ok=True)
    print(f"[pptx-code] {output_file.name}: {changed} code paragraph(s)")
    if not changed:
        print("[pptx-code] No code paragraphs detected; check the deck if code was expected.")


def main():
    args = sys.argv[1:]
    if args:
        if len(args) not in (1, 2):
            raise SystemExit("Usage: python fix_pptx_code.py input.pptx [output.pptx]")
        input_file = Path(args[0]).resolve()
        output_file = Path(args[-1]).resolve()
        fix_pptx(input_file, output_file)
        return

    # Quarto post-render scripts run in the project root. Only touch files
    # listed by Quarto, not reference templates or other existing decks.
    outputs = os.environ.get("QUARTO_PROJECT_OUTPUT_FILES", "")
    list_file = os.environ.get("QUARTO_USE_FILE_FOR_PROJECT_OUTPUT_FILES")
    if list_file:
        outputs = Path(list_file).read_text(encoding="utf-8")
    seen = set()
    for name in outputs.splitlines():
        if not name.strip():
            continue
        path = Path(name.strip()).resolve()
        if path.suffix.lower() != ".pptx" or path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            raise FileNotFoundError(f"Quarto PowerPoint not found: {path}")
        fix_pptx(path, path)


if __name__ == "__main__":
    main()
