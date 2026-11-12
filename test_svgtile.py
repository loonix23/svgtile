#!/usr/bin/env python3
"""Self-test for svgtile. Run: python3 test_svgtile.py"""
import os, shutil, subprocess, sys, tempfile, numpy as np
from pypdf import PdfReader
import re

HERE=os.path.dirname(os.path.abspath(__file__))
def sh(*a):
    r=subprocess.run([sys.executable, os.path.join(HERE,'svgtile.py')]+list(a),
                     capture_output=True, text=True)
    if r.returncode: print(r.stdout, r.stderr); raise SystemExit("svgtile failed")
    return r.stdout

fails=[]
HAVE_PDFTOPPM=bool(shutil.which('pdftoppm'))
DPI=254; cm=lambda v:int(round(v/2.54*DPI))
def render(pdf, page, td):
    """Render one page to a greyscale numpy array via poppler's pdftoppm (binary PGM).
    Row 0 is the TOP of the printed sheet."""
    prefix=os.path.join(td,f'r{page}')
    subprocess.run(['pdftoppm','-gray','-r',str(DPI),'-f',str(page),'-l',str(page),
                    '-singlefile',pdf,prefix], check=True)
    raw=open(prefix+'.pgm','rb').read()
    magic,w,h,maxval=raw.split(maxsplit=4)[:4]
    assert magic==b'P5' and int(maxval)<256
    w,h=int(w),int(h)
    return np.frombuffer(raw[-w*h:],dtype=np.uint8).reshape(h,w)
def ck(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}{'  '+detail if detail else ''}")
    if not cond: fails.append(name)

with tempfile.TemporaryDirectory() as td:
    svg=os.path.join(td,'t.svg')
    open(svg,'w').write('<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="200mm" '
        'viewBox="0 0 300 200"><rect x="0" y="0" width="300" height="200" fill="none" stroke="black"/>'
        '<circle cx="150" cy="100" r="60" fill="none" stroke="black"/></svg>')

    print("\n1. scale detection")
    out=sh(svg,'-o',os.path.join(td,'a.pdf'),'--no-map')
    ck("300mm x 200mm -> 30.00 x 20.00 cm", "30.00 x 20.00" in out)

    print("\n2. rotation")
    o90=sh(svg,'-o',os.path.join(td,'b.pdf'),'--rotate','90','--no-map')
    ck("90 deg swaps dimensions", "20.00 x 30.00" in o90)
    o180=sh(svg,'-o',os.path.join(td,'c.pdf'),'--rotate','180','--no-map')
    ck("180 deg preserves dimensions", "30.00 x 20.00" in o180)
    # 60 x 45 cm SVG page holding only a 25 x 40 cm piece. By the page size rotating
    # looks worse (8 -> 9 sheets); by the actual drawing it saves one (2x2=4 -> 3x1=3).
    ar=os.path.join(td,'ar.svg')
    open(ar,'w').write('<svg xmlns="http://www.w3.org/2000/svg" width="600mm" height="450mm" '
        'viewBox="0 0 600 450"><rect x="10" y="10" width="250" height="400" fill="none" stroke="black"/></svg>')
    oar=sh(ar,'-o',os.path.join(td,'ar.pdf'),'--auto-rotate','--no-map')
    ck("--auto-rotate judges the drawing, not the SVG page", "rotation     90 deg" in oar and
       "= 3 sheets" in oar, re.search(r'grid.*', oar).group(0))

    print("\n3. page geometry")
    rd=PdfReader(os.path.join(td,'a.pdf'))
    w=float(rd.pages[0].mediabox.width)/72*2.54
    h=float(rd.pages[0].mediabox.height)/72*2.54
    ck("A4 page size", abs(w-21)<0.02 and abs(h-29.7)<0.02, f"{w:.3f} x {h:.3f} cm")

    if HAVE_PDFTOPPM:
        # 10 cm reference line on sheet 1: end ticks are 0.3 cm tall, cm ticks only
        # 0.12 (0.2 at 5), so a row 0.25 cm above the line crosses just the end ticks
        S1=render(os.path.join(td,'a.pdf'),1,td)<128
        row=S1[cm(0.5+1.6-0.25), cm(0.5+2.5):cm(0.5+13.5)]
        xs=np.where(row)[0]
        L=None
        if len(xs):
            gap=np.argmax(np.diff(xs)); left,right=xs[:gap+1],xs[gap+1:]
            if len(left) and len(right): L=(right.mean()-left.mean())/DPI*2.54
        ck("10 cm reference line is 10 cm between end ticks",
           L is not None and abs(L-10)<0.01, f"{L:.4f} cm" if L else "ticks not found")

    print("\n4. page order and neighbour labels")
    # 40 x 45 cm drawing -> several rows and columns, so page order matters
    tall=os.path.join(td,'tall.svg')
    open(tall,'w').write('<svg xmlns="http://www.w3.org/2000/svg" width="400mm" height="450mm" '
        'viewBox="0 0 400 450"><rect x="0" y="0" width="400" height="450" fill="none" stroke="black"/></svg>')
    sh(tall,'-o',os.path.join(td,'d.pdf'),'--title','test')
    rd=PdfReader(os.path.join(td,'d.pdf'))
    m=re.search(r'(\d+) across x (\d+) down', rd.pages[0].extract_text())
    NC,NR=int(m.group(1)),int(m.group(2)); n=NC*NR
    ck("test drawing spans several rows", NR>1 and NC>1, f"{NC} x {NR}")
    order=[int(re.search(r'SHEET (\d+) of',pg.extract_text()).group(1)) for pg in rd.pages[1:]]
    ck("pages printed in sheet order 1..n", order==list(range(1,n+1)), str(order))
    bad=0
    for i,pg in enumerate(rd.pages[1:]):
        k=i+1; top_row,c=divmod(i,NC); r=NR-1-top_row   # r counts rows from the bottom
        refs=set(int(x) for x in re.findall(r'shared with sheet (\d+)', pg.extract_text() or ""))
        exp=set()
        if c>0: exp.add(k-1)
        if c<NC-1: exp.add(k+1)
        if r>0: exp.add(k+NC)
        if r<NR-1: exp.add(k-NC)
        if refs!=exp: bad+=1
    ck("all glue-band labels correct", bad==0, f"{n} sheets, {bad} wrong")

    print("\n5. glue bands contain identical artwork")
    sh(svg,'-o',os.path.join(td,'e.pdf'),'--no-band-labels','--no-map','--no-calibration')
    if HAVE_PDFTOPPM:
        epdf=os.path.join(td,'e.pdf')
        A=render(epdf,1,td)<128; B=render(epdf,2,td)<128
        a=A[:,cm(21-0.5-3):cm(21-0.5)]; b=B[:,cm(0.5):cm(0.5+3)]
        k=min(a.shape[1],b.shape[1]); a,b=a[:,:k],b[:,:k]
        d=np.logical_xor(a,b).sum()/max(1,(a.sum()+b.sum()))
        ck("overlap artwork identical", d<0.01, f"{d*100:.2f}% mismatch")
    else:
        print("  [skip] pdftoppm not found (install poppler)")

    print("\n6. transforms")
    tf=os.path.join(td,'tf.svg')
    open(tf,'w').write('<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="100mm" '
        'viewBox="0 0 200 100"><g transform="translate(120,50) scale(2,0.5)">'
        '<circle cx="0" cy="0" r="10" fill="none" stroke="black"/></g></svg>')
    sys.path.insert(0,HERE)
    from svgdoc import load_svg
    p,_,_,_,_=load_svg(tf)
    e=np.array(p[0]['pts'])
    ck("nested translate+scale exact",
       abs((e[:,0].max()-e[:,0].min())-4.0)<1e-6 and abs((e[:,1].max()-e[:,1].min())-1.0)<1e-6,
       f"{e[:,0].max()-e[:,0].min():.4f} x {e[:,1].max()-e[:,1].min():.4f} cm")

    print("\n7. path commands")
    from svgpath import parse_path
    import math
    arc=parse_path('M0,0 A5,5 0 0 1 10,0',60)[0][0]
    err=max(abs(math.hypot(x-5,y)-5) for x,y in arc)
    ck("elliptical arc radius exact", err<1e-9, f"max error {err:.1e}")
    rel=parse_path('m0,0 l10,0 l0,10 z')[0][0]
    ck("relative commands", rel[2]==(10.0,10.0))

    print("\n8. orientation (not mirrored)")
    # Letter F, 10 x 16 cm: stem on the LEFT, 10 cm bar at the TOP, 7 cm bar in the middle.
    fsvg=os.path.join(td,'f.svg')
    open(fsvg,'w').write('<?xml version="1.0"?><!-- comment: must not crash the loader -->'
        '<svg xmlns="http://www.w3.org/2000/svg" width="150mm" height="200mm" viewBox="0 0 150 200">'
        '<!-- another comment --><path d="M20,20 L20,180 M20,20 L120,20 M20,90 L90,90" '
        'stroke="black" fill="none"/></svg>')
    def lines(img):
        """Return (row of 10 cm horizontal bar, rows of 7 cm bar, col of 16 cm line,
        cols of 10 cm vertical, cols of 7 cm vertical) - whatever exists."""
        rows=img.sum(axis=1); cols=img.sum(axis=0)
        near=lambda arr,L: np.where(np.abs(arr-cm(L))<cm(0.6))[0]
        return dict(h10=near(rows,10), h7=near(rows,7), h16=near(rows,16),
                    v10=near(cols,10), v7=near(cols,7), v16=near(cols,16))
    if HAVE_PDFTOPPM:
        flags=['--no-map','--no-calibration','--no-band-labels']
        sh(fsvg,'-o',os.path.join(td,'f0.pdf'),*flags)
        L=lines(render(os.path.join(td,'f0.pdf'),1,td)<128)
        ok=all(len(L[k]) for k in ('h10','h7','v16'))
        ck("upright: long bar above short bar", ok and L['h10'].max()<L['h7'].min())
        ck("upright: stem on the left", ok and L['v16'].max()<cm(6))
        sh(fsvg,'-o',os.path.join(td,'f90.pdf'),'--rotate','90',*flags)
        img=render(os.path.join(td,'f90.pdf'),1,td)<128
        L=lines(img)
        ok=all(len(L[k]) for k in ('v10','v7','h16'))
        # F turned 90 deg counter-clockwise: stem along the bottom, bars pointing up
        # from it, long (former top) bar on the left.
        ck("rotate 90 is counter-clockwise: long bar left of short bar",
           ok and L['v10'].max()<L['v7'].min())
        bar_rows=np.where(img[:,L['v10'][len(L['v10'])//2]])[0] if ok else []
        ck("rotate 90 is counter-clockwise: stem at the bottom, bars point up",
           ok and L['h16'].min()>bar_rows.mean())
    else:
        print("  [skip] pdftoppm not found (install poppler)")

    print("\n9. text")
    # 15 x 20 cm frame on one A4 sheet. The artwork starts at the 0.5 cm margin from the
    # bottom-left paper edge, so point (x,y) mm in the SVG lands at
    # x = 0.5 + x/10 cm from the left, y = 29.7 - 0.5 - 20 + y/10 = 9.2 + y/10 cm from the top.
    tsvg=os.path.join(td,'txt.svg')
    open(tsvg,'w').write('<svg xmlns="http://www.w3.org/2000/svg" width="150mm" height="200mm" viewBox="0 0 150 200">'
        '<rect x="0" y="0" width="150" height="200" fill="none" stroke="black"/>'
        '<text x="20" y="50" font-size="10" font-family="sans-serif">HELLO</text>'
        '<text x="140" y="80" font-size="10" text-anchor="end">END</text>'
        '<g transform="rotate(90 75 120)"><text x="75" y="120" font-size="10">DOWN</text></g>'
        '<text font-size="8"><tspan x="20" y="150">LINE1</tspan><tspan x="20" y="165">LINE2</tspan></text>'
        '<text x="20" y="190" font-size="10"> <!-- c --> </text></svg>')
    def words(pdf):
        """[{word: (xMin, yMin, xMax, yMax) in cm from the top-left}] per page."""
        r=subprocess.run(['pdftotext','-bbox',pdf,'-'],capture_output=True,text=True,check=True).stdout
        return [{m[4]:tuple(float(v)/72*2.54 for v in m[:4]) for m in
                 re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>',pg)}
                for pg in r.split('<page')[1:]]
    near=lambda a,b,tol=0.2: abs(a-b)<tol
    if shutil.which('pdftotext'):
        flags=['--no-map','--no-calibration','--no-band-labels']
        out=sh(tsvg,'-o',os.path.join(td,'t0.pdf'),*flags)
        ck("labels counted, blank text skipped", "text         5 labels" in out)
        W=words(os.path.join(td,'t0.pdf'))[0]
        h=W.get('HELLO')
        ck("HELLO at its SVG position", h and near(h[0],2.5) and h[1]<14.2<h[3], str(h))
        ck("font size kept (10 mm)", h and 0.8<h[3]-h[1]<1.4, f"{h[3]-h[1]:.2f} cm" if h else "")
        e=W.get('END')
        ck("text-anchor=end aligns right edge", e and near(e[2],14.5), str(e))
        d=W.get('DOWN')
        ck("rotated text runs downward from its anchor",
           d and (d[3]-d[1])>2*(d[2]-d[0]) and near(d[1],21.2) and d[0]>7.5, str(d))
        l1,l2=W.get('LINE1'),W.get('LINE2')
        ck("tspan lines 1.5 cm apart", l1 and l2 and near(l2[1]-l1[1],1.5,0.05))
        sh(tsvg,'-o',os.path.join(td,'t90.pdf'),'--rotate','90',*flags)
        h=words(os.path.join(td,'t90.pdf'))[0].get('HELLO')
        ck("--rotate 90 turns text with the artwork", h and (h[3]-h[1])>2*(h[2]-h[0]), str(h))
        sh(tsvg,'-o',os.path.join(td,'t15.pdf'),'--scale-factor','1.5',*flags)
        ws=[w['HELLO'] for w in words(os.path.join(td,'t15.pdf')) if 'HELLO' in w]
        w0=W['HELLO'][2]-W['HELLO'][0]
        ck("--scale-factor scales text", ws and near((ws[0][2]-ws[0][0])/w0,1.5,0.03))
        sh(tsvg,'-o',os.path.join(td,'tn.pdf'),'--no-text',*flags)
        ck("--no-text omits text",
           not {'HELLO','END','DOWN','LINE1','LINE2'} & set(words(os.path.join(td,'tn.pdf'))[0]))
    else:
        print("  [skip] pdftotext not found (install poppler)")

print("\n10. standalone build")
r=subprocess.run([sys.executable, os.path.join(HERE,'build_standalone.py'),'--check'],
                 capture_output=True, text=True)
ck("svgtile-standalone.py matches modules", r.returncode==0,
   "" if r.returncode==0 else "run: python3 build_standalone.py")

print("\n"+("ALL TESTS PASSED" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
