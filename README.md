# svgtile

Split an SVG into glue-together paper sheets (A4, Letter, A3 or Legal) at
**true 1:1 scale**. Built for sewing patterns: vector output, monochrome
(laser-printer safe), and registration marks that are guaranteed to pair up for
light-table alignment.

Example: [`examples/demo.svg`](examples/demo.svg), a 35 × 25 cm test drawing,
tiles to [`examples/demo.pdf`](examples/demo.pdf), an assembly map plus 2 A4
sheets. Print it to check your printer before printing a real pattern:

```bash
python3 svgtile.py examples/demo.svg -o examples/demo.pdf --title "svgtile demo"
```

## Install

Two layouts; pick one.

**Single file (recommended for a `~/tools` style PATH directory):**

```bash
install -Dm755 svgtile-standalone.py ~/tools/svgtile
svgtile pattern.svg
```

**Multi-file** — keep `svgtile.py`, `svgdoc.py` and `svgpath.py` together in the
same directory. Python puts the script's own directory first on the import path,
so the sibling imports resolve (this also works through a symlink):

```bash
cp svgtile.py svgdoc.py svgpath.py ~/tools/
chmod +x ~/tools/svgtile.py
mv ~/tools/svgtile.py ~/tools/svgtile
```

`svgtile-standalone.py` is generated from the three modules by
`python3 build_standalone.py`. Don't edit it directly.

Note this drops `svgdoc.py` and `svgpath.py` — generic names — into a PATH
directory. Harmless (they aren't executable), but the single file avoids it.

### Dependencies

svgtile needs Python 3 with `reportlab` and `lxml`:

```bash
pip install reportlab lxml
```

The self-test (`test_svgtile.py`) also needs `pypdf`, `numpy` and poppler's
`pdftoppm`.

On Arch, `pip install` into the system Python is blocked by PEP 668. Use pacman:

```bash
sudo pacman -S python-reportlab python-lxml
```

Optional, for `test_svgtile.py` only:

```bash
sudo pacman -S python-pypdf python-numpy poppler
```

Or keep it isolated in a venv:

```bash
python3 -m venv ~/.venvs/svgtile
~/.venvs/svgtile/bin/pip install reportlab lxml
```
then point the script's shebang at `~/.venvs/svgtile/bin/python3`, or install
with `pipx install --include-deps`.

## Usage

```bash
python3 svgtile.py pattern.svg                       # -> pattern_tiled.pdf
python3 svgtile.py pattern.svg -o out.pdf --rotate 90
python3 svgtile.py pattern.svg --auto-rotate         # rotate only if it saves sheets
python3 svgtile.py pattern.svg --page a3 --overlap 4
python3 svgtile.py pattern.svg --page letter         # US Letter paper
```

## Scale — read this first

A pattern that prints at 97% is worthless, so scale is resolved explicitly and
the basis is always reported:

```
artwork      30.00 x 20.00 cm
scale basis  width/height (300mm x 200mm) vs viewBox
```

Resolution order:

1. `--scale N` — force N cm per SVG user unit. Overrides everything.
2. Root `width`/`height` in real units (`mm`, `cm`, `in`, `pt`, `pc`) against `viewBox`. Best case.
3. `width`/`height` in `px` — converted at `--dpi` (default 96, the CSS standard).
4. No physical size at all — falls back to `--dpi` and **says so**. Verify this one.

If `width`/`height` disagree in aspect ratio with `viewBox`, you get a
`WARNING: non-uniform scale` line. For a sewing pattern that almost always means
the SVG is wrong — one axis will be stretched.

### Paper size

Tile for the paper you will actually print on. A4 is the default; use
`--page letter` for US Letter. An A4 PDF printed on Letter paper does not fit:
Letter is 1.8 cm shorter, so the printer either cuts off the edge or shrinks the
page to fit, and shrinking breaks the 1:1 scale. When sharing a pattern, publish
one PDF per paper size.

**Always measure the calibration marks on sheet 1 before cutting fabric.** The
2 cm square shows gross scaling (a print dialog's ~4% shrink). The 10 cm
reference line shows the small scaling some printers add on their own: 0.5% is
only 0.1 mm on the square but 0.5 mm on the line. Measure between its end
ticks; it should read 99.5–100.5 mm.

### Printing at 100%

The PDF is exact; print dialogs often aren't. Because artwork runs to within
5 mm of the paper edge, many viewers and CUPS drivers silently "shrink to
printable area" — even with 100% selected. A ~4% shrink (calibration square
reads 19.2 mm instead of 20 mm) is the telltale sign.

In the print dialog, set page scaling to **None / Actual size** and untick
"Shrink oversized pages" / "Fit to printable area". Or skip the viewer and print
directly with CUPS:

```bash
lpstat -e                                # list printer queues
lpoptions -d <printer>                   # optional: make one the default
lp -d <printer> -o fit-to-page=false -o print-scaling=none sheets.pdf
lp ... -o page-ranges=2-                 # skip the assembly map page
```

If the square is still short, the driver itself is scaling: regenerate with a
larger `--margin` (e.g. `--margin 1`) so the artwork sits inside the printer's
printable area.

`--scale-factor 1.05` enlarges the finished artwork by 5% (seam allowance
experiments, shrinkage compensation). It is *not* a scale fix — fix the source.

## Assembly model

The default assumes **no trimming**: artwork runs to within `--margin` (default
5 mm) of the paper edge, and neighbouring sheets share an `--overlap` band
(default 3 cm) of identical artwork. With the margins on both sheets, the paper
itself overlaps by `2 × margin + overlap` (4 cm by default).

The dash-dot **glue line** on each sheet is drawn that far from the edge, where
the neighbour's *paper edge* lands. Lay one sheet over the next on a light
table, put its edge on the line for a rough fit, align the registration marks,
glue.

Each mark is a cross-in-circle labelled with its **master coordinate**
(e.g. `34,18`). The marks are generated in master space and every mark falling
inside a shared band is emitted by *both* sheets — so pairing is structural, and
matching numbers confirm correct alignment rather than guesswork.

For cut-and-butt assembly instead, use `--trim-marks` to get corner crop marks.

Your printer's unprintable border (~5 mm) means the top sheet covers a thin strip
of the one beneath. Cut lines are smooth so bridging by eye is easy; trim that
edge if you want perfect continuity.

## Options

| flag | meaning |
|---|---|
| `--rotate 0\|90\|180\|270` | rotate artwork before tiling (CCW) |
| `--auto-rotate` | rotate 90° only if it reduces the sheet count |
| `--page a4\|a3\|letter\|legal` / `--landscape` | paper size |
| `--overlap N` | glue band width, cm (default 3) |
| `--margin N` | unprintable border, cm (default 0.5) |
| `--trim-marks` | add corner crop marks for cut-and-butt assembly |
| `--dpi N` | user-units per inch when the SVG has no physical size |
| `--scale N` | force N cm per user unit |
| `--scale-factor N` | enlarge/shrink finished artwork |
| `--curve-steps N` | curve flattening quality (default 24) |
| `--line-width N` | default stroke width, pt |
| `--mark-spacing N` | cm between registration marks (default 4) |
| `--no-band-labels` | omit glue-band lines/labels for cleaner sheets |
| `--no-map` / `--no-calibration` | omit the map page / calibration square and reference line |
| `--no-text` | omit the SVG's text |

## SVG support

Handled: `path` (all commands incl. elliptical arcs, absolute and relative),
`line`, `polyline`, `polygon`, `rect` (incl. rounded), `circle`, `ellipse`,
nested `g`, and `transform` (`matrix`, `translate`, `scale`, `rotate` with or
without centre, `skewX`, `skewY`). `stroke-dasharray` is preserved.

`text` and positioned `tspan` (multi-line text) are printed in black, with
`font-size`, `text-anchor` and any rotation from transforms. Skewed or unevenly
stretched text is approximated by size and angle only. The font named in
`font-family` is embedded when a TrueType file for it is found: via fontconfig,
the usual font directories, or FreeCAD's TechDraw font folder (so FreeCAD's
`osifont` works without installing it). Otherwise Helvetica is used. The run
summary lists which font file was used for each family.

Not handled: images, gradients, clip paths,
filters, CSS stylesheets, `use`/`symbol` references. Everything prints as black
strokes — fills are ignored, which is what you want for a cutting pattern.

Tiling covers the **artwork bounding box**, not the declared canvas, so empty
margins don't cost you sheets.

## Self-test

```bash
python3 test_svgtile.py
```

Checks scale resolution, rotation, page geometry, neighbour labelling, transform
accuracy, arc geometry, and — end to end — that overlapping sheets render
pixel-identical artwork in their shared glue band.

## License

MIT, see [LICENSE](LICENSE).
