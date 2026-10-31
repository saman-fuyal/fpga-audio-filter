#!/usr/bin/env python3
"""Turn a Vivado schematic PDF (write_schematic -format pdf) into a black-on-white PNG for the paper.

    py docs\\report\\prep_schematic.py C:/Users/ACER/Desktop/rtl_dc.pdf
    -> docs/report/figs/user/rtl_dc.png            (one PNG per PDF, nothing is overwritten)
    py docs\\report\\prep_schematic.py C:/Users/ACER/Desktop/rtl_dc.pdf --use
    -> also copies it to docs/report/figs/user/rtl_schematic.png, the file the paper uses

What it does: renders the PDF at high resolution, turns Vivado's colours into pure black line
art (light block fills become white; green wires, outlines and text become black), crops the
white margin, turns the drawing upright if Vivado rotated it onto a landscape page, and
saves it at a width that stays sharp in one column of the paper.

Needs:  py -m pip install pypdfium2 pillow
Options: --use  --rotate {auto,0,90,-90}  --out <png>  --width <px>  --threshold <0-255>
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
USER_DIR = os.path.join(HERE, "figs", "user")
PAPER_FIG = os.path.join(USER_DIR, "rtl_schematic.png")


def render(pdf, dpi):
    """First page of the PDF as a PIL image (pypdfium2; falls back to pdf2image/poppler)."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf)
        page = doc[0]
        page.set_rotation(0)        # Vivado stores landscape schematics as a portrait page turned by 270 degrees
        return page.render(scale=dpi / 72.0).to_pil()
    except ImportError:
        try:
            from pdf2image import convert_from_path
            return convert_from_path(pdf, dpi=dpi, first_page=1, last_page=1)[0]
        except ImportError:
            sys.exit("install a PDF renderer first:  py -m pip install pypdfium2")


def label_size_pt(pdf):
    """Median label height on the Vivado page, from the [ and ] glyphs of bus names (about one em)."""
    try:
        import pypdfium2 as pdfium, statistics
        page = pdfium.PdfDocument(pdf)[0]
        tp = page.get_textpage()
        text = tp.get_text_range()
        hs = []
        for i, ch in enumerate(text):
            if ch in "[]":
                l, b, r, t = tp.get_charbox(i)
                hs.append(max(r - l, t - b))
        return statistics.median(hs) if hs else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default=None, help="output PNG (default: figs/user/<pdf name>.png)")
    ap.add_argument("--use", action="store_true", help="also make it the paper figure (rtl_schematic.png)")
    ap.add_argument("--rotate", default="auto", choices=["auto", "0", "90", "-90"])
    ap.add_argument("--width", type=int, default=2400, help="output width in pixels")
    ap.add_argument("--threshold", type=int, default=215,
                    help="grey level above which a pixel counts as background (block fills)")
    ap.add_argument("--dpi", type=int, default=600)
    a = ap.parse_args()
    if a.out is None:
        a.out = os.path.join(USER_DIR, os.path.splitext(os.path.basename(a.pdf))[0] + ".png")

    from PIL import Image, ImageOps
    im = render(a.pdf, a.dpi).convert("RGB")
    g = im.convert("L")
    # Vivado fills (light blue, light yellow) are bright; wires (green), outlines and text are dark.
    bw = g.point(lambda v: 255 if v >= a.threshold else 0, mode="L")
    box = ImageOps.invert(bw).getbbox()
    if box is None:
        sys.exit("the PDF page is empty")
    m = 30
    box = (max(box[0] - m, 0), max(box[1] - m, 0), min(box[2] + m, bw.width), min(box[3] + m, bw.height))
    bw = bw.crop(box)
    rot = a.rotate
    if rot == "auto":
        rot = "0"                   # page rotation is already undone in render(); use --rotate if still sideways
    if rot != "0":
        bw = bw.rotate(int(rot), expand=True, fillcolor=255)
    drawing_pt = bw.width * 72.0 / a.dpi          # width of the drawing on the Vivado page
    if bw.width > a.width:
        h = round(bw.height * a.width / bw.width)
        bw = bw.resize((a.width, h), Image.LANCZOS)
        bw = bw.point(lambda v: 255 if v >= 200 else (0 if v < 110 else v))   # keep thin lines solid
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    bw.save(a.out, dpi=(600, 600))
    print(f"written {a.out}  ({bw.width} x {bw.height} px, rotated {rot})")
    if a.use:
        import shutil
        shutil.copyfile(a.out, PAPER_FIG)
        print(f"copied to {PAPER_FIG} (the paper figure)")
    # readability check: how large the labels will print in one column and across both columns
    lab = label_size_pt(a.pdf)
    for name, width_pt in (("one column", 243.0), ("both columns", 504.0)):
        scale = min(width_pt / drawing_pt, 1.0)
        if lab:
            print(f"{name}: labels print at about {lab * scale:.1f} pt "
                  f"({'readable' if lab * scale >= 5 else 'too small, need at least 5 pt'})")
        else:
            print(f"{name}: drawing prints at {100 * scale:.0f}% of its Vivado size")

if __name__ == "__main__":
    main()
