#!/usr/bin/env python3
"""
svgtile - split an SVG into glue-together A4 (or Letter/A3) PDF sheets.

Designed for sewing patterns: preserves true 1:1 scale, stays vector, and prints
monochrome with paired registration marks suitable for light-table alignment.

  python3 svgtile.py pattern.svg -o pattern_a4.pdf
  python3 svgtile.py pattern.svg --rotate 90 --overlap 3 --no-trim
"""
import argparse, glob, math, os, shutil, subprocess, sys
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.colors import black, Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from svgdoc import load_svg

CM = 28.3464566929  # postscript points per cm

PAGES = {  # width_cm, height_cm  (portrait)
    'a4':(21.0,29.7), 'a3':(29.7,42.0), 'letter':(21.59,27.94), 'legal':(21.59,35.56),
}

# ---------------------------------------------------------------- geometry
def rotate90(polys, texts, W, H, times):
    """Rotate CCW by 90*times (y-up coordinates), keeping the drawing in the
    positive quadrant. Returns polys, texts, newW, newH."""
    times%=4
    for _ in range(times):
        polys=[dict(p, pts=[(H-y, x) for (x,y) in p['pts']]) for p in polys]
        texts=[dict(t, x=H-t['y'], y=t['x'], angle=t['angle']+90) for t in texts]
        W,H = H,W
    return polys, texts, W, H

def transform(polys, texts, f=1.0, dx=0.0, dy=0.0):
    """Scale by f about the origin, then shift by (dx,dy)."""
    polys=[dict(p, pts=[(x*f+dx, y*f+dy) for x,y in p['pts']]) for p in polys]
    texts=[dict(t, x=t['x']*f+dx, y=t['y']*f+dy, size=t['size']*f) for t in texts]
    return polys, texts

def text_corners(t):
    """The four corners of a text's box (baseline-anchored, descender to ascender), cm."""
    w=pdfmetrics.stringWidth(t['text'], t['font'], t['size']*CM)/CM
    x0={'middle':-w/2,'end':-w}.get(t['anchor'],0.0)
    a=math.radians(t['angle']); ca,sa=math.cos(a),math.sin(a)
    return [(t['x']+u*ca-v*sa, t['y']+u*sa+v*ca)
            for u in (x0,x0+w) for v in (-0.25*t['size'], 0.8*t['size'])]

def bbox(polys, texts=()):
    pts=[q for p in polys for q in p['pts']]+[q for t in texts for q in text_corners(t)]
    xs=[x for x,_ in pts]; ys=[y for _,y in pts]
    return (min(xs),min(ys),max(xs),max(ys)) if xs else (0,0,0,0)

def tile_starts(total, span, step):
    s=[0.0]; cov=span
    while cov < total - 1e-9:
        s.append(cov-(span-step)); cov+=step
    return s

# ---------------------------------------------------------------- fonts
# Where to look for a TrueType file when fontconfig doesn't know the family.
# FreeCAD ships its TechDraw fonts (osifont, ...) here without registering them.
FONT_DIRS=['~/.local/share/fonts','~/.fonts','/usr/share/fonts','/usr/local/share/fonts',
           '/usr/share/freecad*/Mod/TechDraw/Resources/fonts',
           '/usr/lib/freecad*/Mod/TechDraw/Resources/fonts',
           '/usr/lib64/freecad*/Mod/TechDraw/Resources/fonts',
           '/opt/freecad*/**/Mod/TechDraw/Resources/fonts',
           '/Applications/FreeCAD.app/Contents/Resources/Mod/TechDraw/Resources/fonts']
BUILTIN={'sans-serif':'Helvetica','sans':'Helvetica','arial':'Helvetica','helvetica':'Helvetica',
         'serif':'Times-Roman','times':'Times-Roman','times new roman':'Times-Roman',
         'monospace':'Courier','courier':'Courier','courier new':'Courier'}
BOLD={'Helvetica':'Helvetica-Bold','Times-Roman':'Times-Bold','Courier':'Courier-Bold'}

def find_font_file(family):
    """TrueType file for a font family, or None."""
    fam=family.lower()
    if shutil.which('fc-match'):
        r=subprocess.run(['fc-match','-f','%{family}|%{file}',family],capture_output=True,text=True)
        names,_,path=r.stdout.partition('|')
        if fam in [n.strip().lower() for n in names.split(',')] and path.lower().endswith('.ttf'):
            return path
    hits=[]
    for pat in FONT_DIRS:
        for d in glob.glob(os.path.expanduser(pat), recursive=True):
            for f in glob.glob(os.path.join(d,'**','*.ttf'), recursive=True):
                b=os.path.basename(f).lower()
                if b.startswith(fam.replace(' ','')) and not any(x in b for x in ('italic','oblique','bold')):
                    hits.append(f)
    return min(hits, key=lambda f:len(os.path.basename(f))) if hits else None

def resolve_fonts(texts):
    """Set t['font'] to a registered reportlab font name. Returns {family: description}."""
    report={}; cache={}
    for t in texts:
        fam=t['family']
        if fam not in cache:
            name=None
            path=None if fam.lower() in BUILTIN else find_font_file(fam)
            if path:
                try:
                    name='svgtile-'+fam
                    pdfmetrics.registerFont(TTFont(name, path)); report[fam]=path
                except Exception as e:   # e.g. CFF-flavoured .ttf, broken file
                    name=None; report[fam]=f"{path} unusable ({e}) -> Helvetica"
            if not name:
                name=BUILTIN.get(fam.lower(),'Helvetica')
                report.setdefault(fam, name if fam.lower() in BUILTIN else f"not found -> {name}")
            cache[fam]=name
        t['font']=BOLD.get(cache[fam],cache[fam]) if t['bold'] else cache[fam]
    return report

# ---------------------------------------------------------------- marks
def build_marks(CS, RS, span_w, span_h, overlap, MW, MH, spacing=4.0, min_sep=2.8):
    """Registration marks on glue-band centrelines, defined in MASTER space so the
    same mark is emitted by both sheets sharing a band (guaranteed pairing)."""
    vs=[CS[c+1]+overlap/2 for c in range(len(CS)-1)]
    hs=[RS[r+1]+overlap/2 for r in range(len(RS)-1)]
    marks=[]
    for vx in vs:
        y=spacing/2
        while y<MH: marks.append((vx,y)); y+=spacing
    for hy in hs:
        x=spacing/2
        while x<MW: marks.append((x,hy)); x+=spacing
    marks=sorted({(round(a,3),round(b,3)) for a,b in marks})
    kept=[]
    for m in marks:
        if all((m[0]-k[0])**2+(m[1]-k[1])**2 >= min_sep**2 for k in kept): kept.append(m)
    return kept, vs, hs

# ---------------------------------------------------------------- drawing
def draw_mark(c, X, Y, label, mono=True):
    R=0.42
    c.setLineWidth(0.7); c.setStrokeColor(black)
    c.circle(X*CM, Y*CM, R*CM, stroke=1, fill=0)
    c.line((X-R*1.75)*CM, Y*CM, (X+R*1.75)*CM, Y*CM)
    c.line(X*CM, (Y-R*1.75)*CM, X*CM, (Y+R*1.75)*CM)
    c.setFillColor(black); c.circle(X*CM, Y*CM, 0.07*CM, stroke=0, fill=1)
    if label:
        c.setFont('Courier',4.4); c.drawString((X+R*1.9)*CM,(Y+R*0.55)*CM, label)

def dash_for(p, mono):
    d=p.get('dash')
    if d and d not in ('none','None'):
        try:
            vals=[float(v)*CM for v in d.replace(',',' ').split()]
            if vals: return vals
        except ValueError: pass
    return None

def draw_polys(c, polys, ox, oy, mono, default_lw):
    for p in polys:
        pts=p['pts']
        if len(pts)<2: continue
        lw=default_lw
        if p.get('width'):
            try: lw=max(0.15, float(str(p['width']).replace('px','')) * 0.35)
            except ValueError: pass
        c.setLineWidth(lw)
        c.setStrokeColor(black)
        d=dash_for(p,mono)
        c.setDash(d if d else [])
        path=c.beginPath()
        path.moveTo((pts[0][0]+ox)*CM, (pts[0][1]+oy)*CM)
        for x,y in pts[1:]:
            path.lineTo((x+ox)*CM, (y+oy)*CM)
        if p.get('closed'): path.close()
        c.drawPath(path, stroke=1, fill=0)
    c.setDash([])

def draw_texts(c, texts, ox, oy):
    c.setFillColor(black)
    for t in texts:
        c.saveState()
        c.translate((t['x']+ox)*CM, (t['y']+oy)*CM); c.rotate(t['angle'])
        c.setFont(t['font'], t['size']*CM)
        {'middle':c.drawCentredString,'end':c.drawRightString}.get(t['anchor'],c.drawString)(0,0,t['text'])
        c.restoreState()

# ---------------------------------------------------------------- main
def main():
    ap=argparse.ArgumentParser(description="Split an SVG into glue-together A4 PDF sheets at true 1:1 scale.")
    ap.add_argument('svg')
    ap.add_argument('-o','--output', help='output PDF (default: <input>_tiled.pdf)')
    ap.add_argument('--rotate', type=int, default=0, choices=[0,90,180,270],
                    help='rotate artwork before tiling (degrees CCW)')
    ap.add_argument('--auto-rotate', action='store_true',
                    help='rotate 90 automatically if it reduces the sheet count')
    ap.add_argument('--page', default='a4', choices=sorted(PAGES))
    ap.add_argument('--landscape', action='store_true')
    ap.add_argument('--overlap', type=float, default=3.0, help='glue band width in cm (default 3)')
    ap.add_argument('--margin', type=float, default=0.5,
                    help='unprintable border in cm (default 0.5 = near full-bleed, no trimming)')
    ap.add_argument('--trim-marks', action='store_true',
                    help='add corner crop marks (for cut-and-butt assembly instead of overlap gluing)')
    ap.add_argument('--dpi', type=float, default=96.0,
                    help='user-units per inch when the SVG has no physical size (default 96)')
    ap.add_argument('--scale', type=float, default=None,
                    help='force N cm per SVG user unit (overrides all size detection)')
    ap.add_argument('--scale-factor', type=float, default=1.0,
                    help='enlarge/shrink the finished artwork, e.g. 1.05 for +5%%')
    ap.add_argument('--curve-steps', type=int, default=24, help='curve flattening quality')
    ap.add_argument('--line-width', type=float, default=0.9, help='default stroke width in pt')
    ap.add_argument('--mark-spacing', type=float, default=4.0, help='cm between registration marks')
    ap.add_argument('--no-map', action='store_true', help='skip the assembly map page')
    ap.add_argument('--no-band-labels', action='store_true',
                    help='omit glue-band boundary lines and labels (cleaner sheets; '
                         'also makes overlapping sheets pixel-identical in the band)')
    ap.add_argument('--no-calibration', action='store_true', help='skip the 2 cm calibration square')
    ap.add_argument('--no-text', action='store_true', help='omit the SVG\'s text')
    ap.add_argument('--title', default=None, help='title printed on the map page')
    a=ap.parse_args()

    if not os.path.exists(a.svg): sys.exit(f"error: no such file: {a.svg}")
    out=a.output or os.path.splitext(a.svg)[0]+'_tiled.pdf'

    polys,texts,W,H,info = load_svg(a.svg, dpi=a.dpi, curve_steps=a.curve_steps, scale_override=a.scale)
    if a.no_text: texts=[]
    if not polys and not texts:
        sys.exit("error: no drawable geometry found in the SVG "
                 "(only path/line/polyline/polygon/rect/circle/ellipse/text are supported)")
    fonts=resolve_fonts(texts)
    if a.scale_factor!=1.0:
        polys,texts=transform(polys,texts,a.scale_factor)
        W*=a.scale_factor; H*=a.scale_factor

    PW,PH = PAGES[a.page]
    if a.landscape: PW,PH = PH,PW

    def sheets_for(w,h):
        uw,uh = PW-2*a.margin, PH-2*a.margin
        if uw<=a.overlap or uh<=a.overlap: return 10**6,0,0
        sx,sy = uw-a.overlap, uh-a.overlap
        return len(tile_starts(w,uw,sx))*len(tile_starts(h,uh,sy)), uw, uh

    rot = a.rotate//90
    if a.auto_rotate:
        # judge the drawing itself, not the SVG page it sits on; a 90 deg turn swaps its sides
        x0,y0,x1,y1 = bbox(polys,texts)
        if sheets_for(y1-y0,x1-x0)[0] < sheets_for(x1-x0,y1-y0)[0]: rot=1
    if rot:
        polys,texts,W,H = rotate90(polys,texts,W,H,rot)

    # normalise to origin
    x0,y0,x1,y1 = bbox(polys,texts)
    # master space = the artwork's bounding box; each sheet adds the paper margin itself
    polys,texts = transform(polys,texts,1.0,-x0,-y0)
    MW, MH = x1-x0, y1-y0

    USE_W, USE_H = PW-2*a.margin, PH-2*a.margin
    if USE_W<=a.overlap or USE_H<=a.overlap:
        sys.exit("error: overlap is too large for the page size")
    STEP_X, STEP_Y = USE_W-a.overlap, USE_H-a.overlap
    CS = tile_starts(MW, USE_W, STEP_X)
    RS = tile_starts(MH, USE_H, STEP_Y)
    NC, NR = len(CS), len(RS)
    MARKS, VS, HS = build_marks(CS,RS,USE_W,USE_H,a.overlap,MW,MH,a.mark_spacing)

    def sheet_no(r,c): return (NR-1-r)*NC + c + 1   # 1 = top-left, reading order

    c=rl_canvas.Canvas(out, pagesize=(PW*CM, PH*CM))
    c.setTitle(a.title or os.path.basename(a.svg))

    # ---------------- assembly map ----------------
    if not a.no_map:
        sc=min((PW-3)/MW, (PH*0.60-2)/MH)
        ox=(PW-MW*sc)/2; oy=PH*0.36
        c.setFont('Helvetica-Bold',11)
        c.drawCentredString(PW/2*CM,(PH-1.3)*CM, f"ASSEMBLY MAP - {NC*NR} sheets ({NC} across x {NR} down)")
        c.setFont('Helvetica',8)
        c.drawCentredString(PW/2*CM,(PH-1.85)*CM, "sheet 1 = TOP-LEFT, numbered left to right")
        c.saveState(); c.translate(ox*CM,oy*CM); c.scale(sc,sc)
        c.setLineWidth(0.8/sc)
        for p in polys:
            pts=p['pts']
            if len(pts)<2: continue
            pa=c.beginPath(); pa.moveTo(pts[0][0]*CM,pts[0][1]*CM)
            for x,y in pts[1:]: pa.lineTo(x*CM,y*CM)
            if p.get('closed'): pa.close()
            c.drawPath(pa,stroke=1,fill=0)
        draw_texts(c, texts, 0, 0)
        c.setLineWidth(0.6/sc); c.setDash([3/sc,2/sc])
        for r,ry in enumerate(RS):
            for cc,cx0 in enumerate(CS):
                x1_,y1_=min(cx0+USE_W,MW),min(ry+USE_H,MH)
                c.rect(cx0*CM,ry*CM,(x1_-cx0)*CM,(y1_-ry)*CM,stroke=1,fill=0)
        c.setDash([])
        c.setFont('Helvetica-Bold',max(5,8/sc))
        for r,ry in enumerate(RS):
            for cc,cx0 in enumerate(CS):
                c.drawString((cx0+0.4)*CM, (min(ry+USE_H,MH)-1.2)*CM, str(sheet_no(r,cc)))
        c.restoreState()
        tx=1.2; ty=PH*0.34
        lines=[
            (a.title or os.path.basename(a.svg)),
            "",
            f"Artwork {MW:.1f} x {MH:.1f} cm   ->   {NC*NR} sheets of {a.page.upper()}"
            f"{' landscape' if a.landscape else ''}",
            f"Scale basis: {info['basis']}",
            f"Rotation applied: {rot*90} deg" if rot else "Rotation applied: none",
            "",
            "PRINTING: 100% / \"Actual Size\". NOT \"Fit to page\".",
            ("Sheet 1 carries a 2 cm calibration square - measure it before cutting."
             if not a.no_calibration else ""),
            "",
            "ASSEMBLY - NO TRIMMING NEEDED:" if not a.trim_marks else "ASSEMBLY - TRIM AT CROP MARKS:",
            (f"  Artwork runs to within {a.margin*10:.0f} mm of the paper edge and every sheet"
             if not a.trim_marks else "  Trim each sheet on the corner crop marks, then butt them together."),
            (f"  overlaps its neighbour by {a.overlap:.0f} cm, so sheets glue as printed."
             if not a.trim_marks else ""),
            "  Each registration mark is a CROSS IN A CIRCLE labelled with its master",
            "  coordinate. The SAME mark and number is printed on BOTH sheets sharing a",
            "  glue band - lay the crosses on top of each other on a light table, check",
            "  the numbers agree, then glue. Work along the top row, then each row below.",
            "",
            "No colour is used anywhere - safe for a monochrome laser printer.",
        ]
        c.setFont('Courier',7)
        for ln in lines:
            if ln: c.drawString(tx*CM, ty*CM, ln)
            ty-=0.42
        c.showPage()

    # ---------------- tiles ----------------
    for r in reversed(range(NR)):        # top row first, so pages come out as sheet 1..n
        y0_=RS[r]
        for cc,x0_ in enumerate(CS):
            k=sheet_no(r,cc)
            ox,oy = a.margin-x0_, a.margin-y0_
            draw_polys(c, polys, ox, oy, True, a.line_width)
            draw_texts(c, texts, ox, oy)

            px1 = a.margin+min(USE_W, MW-x0_)
            py1 = a.margin+min(USE_H, MH-y0_)
            # glue band boundaries
            if not a.no_band_labels:
             c.setLineWidth(0.6); c.setDash([6,2,1,2]); c.setStrokeColor(black)
             c.setFont('Helvetica',5.2)
             if cc>0:
                 gx=a.margin+a.overlap
                 c.line(gx*CM,0,gx*CM,PH*CM)
                 c.saveState(); c.translate((gx-0.15)*CM,(PH/2)*CM); c.rotate(90)
                 c.drawRightString(0,0,f"<- {a.overlap:.0f} cm GLUE BAND shared with sheet {k-1}"); c.restoreState()
             if cc<NC-1:
                 gx=PW-a.margin-a.overlap
                 c.line(gx*CM,0,gx*CM,PH*CM)
                 c.saveState(); c.translate((gx+0.15)*CM,(PH/2)*CM); c.rotate(90)
                 c.drawString(0,0,f"{a.overlap:.0f} cm GLUE BAND shared with sheet {k+1} ->"); c.restoreState()
             # page BOTTOM = low master y -> neighbour is the row below (exists when r>0),
             # which prints as a HIGHER sheet number (k+NC).
             if r>0:
                 gy=a.margin+a.overlap
                 c.line(0,gy*CM,PW*CM,gy*CM)
                 c.drawCentredString((PW/2)*CM,(gy-0.32)*CM,f"v {a.overlap:.0f} cm GLUE BAND shared with sheet {k+NC}")
             # page TOP = high master y -> neighbour is the row above (exists when r<NR-1) = k-NC
             if r<NR-1:
                 gy=PH-a.margin-a.overlap
                 c.line(0,gy*CM,PW*CM,gy*CM)
                 c.drawCentredString((PW/2)*CM,(gy+0.18)*CM,f"^ {a.overlap:.0f} cm GLUE BAND shared with sheet {k-NC}")
             c.setDash([])

            if a.trim_marks:
                c.setLineWidth(0.6)
                for (mx,my) in [(a.margin,a.margin),(px1,a.margin),(a.margin,py1),(px1,py1)]:
                    c.line((mx-0.5)*CM,my*CM,(mx+0.5)*CM,my*CM)
                    c.line(mx*CM,(my-0.5)*CM,mx*CM,(my+0.5)*CM)

            for (mx,my) in MARKS:
                PX,PY = mx+ox, my+oy
                if -0.6<PX<PW+0.6 and -0.6<PY<PH+0.6:
                    draw_mark(c,PX,PY,f"{mx:.0f},{my:.0f}")

            if k==1 and not a.no_calibration:
                c.setLineWidth(1.2); c.setStrokeColor(black)
                c.rect((a.margin+0.4)*CM,(PH-a.margin-2.6)*CM,2*CM,2*CM,stroke=1,fill=0)
                c.setFont('Helvetica',5)
                c.drawString((a.margin+0.4)*CM,(PH-a.margin-3.0)*CM,
                             "2 cm CALIBRATION SQUARE - measure before cutting")

            c.setFont('Helvetica-Bold',7.5)
            c.drawCentredString((PW/2)*CM,(PH-0.42)*CM,
                                f"SHEET {k} of {NC*NR}   (row {r+1} from bottom, col {cc+1})")
            if not a.no_band_labels:
                c.setFont('Helvetica',5)
                c.drawString(a.margin*CM, 0.22*CM, f"{os.path.basename(a.svg)} - print at 100%")
            c.showPage()
    c.save()

    print(f"artwork      {MW:.2f} x {MH:.2f} cm")
    print(f"scale basis  {info['basis']}")
    if info['nonuniform']:
        print(f"WARNING      non-uniform scale (x {info['k_x']:.5f} vs y {info['k_y']:.5f} cm/unit)")
    if rot: print(f"rotation     {rot*90} deg")
    print(f"grid         {NC} x {NR} = {NC*NR} sheets ({a.page.upper()}), {a.overlap} cm overlap")
    print(f"marks        {len(MARKS)} registration marks")
    if texts:
        print(f"text         {len(texts)} labels")
        for fam,desc in fonts.items(): print(f"font         {fam}: {desc}")
    print(f"written      {out}")

if __name__=='__main__': main()
