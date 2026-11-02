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

    print("\n3. page geometry")
    rd=PdfReader(os.path.join(td,'a.pdf'))
    w=float(rd.pages[0].mediabox.width)/72*2.54
    h=float(rd.pages[0].mediabox.height)/72*2.54
    ck("A4 page size", abs(w-21)<0.02 and abs(h-29.7)<0.02, f"{w:.3f} x {h:.3f} cm")

    print("\n4. neighbour labels reference real sheets")
    sh(svg,'-o',os.path.join(td,'d.pdf'),'--title','test')
    rd=PdfReader(os.path.join(td,'d.pdf'))
    m=re.search(r'(\d+) across x (\d+) down', rd.pages[0].extract_text())
    NC,NR=int(m.group(1)),int(m.group(2)); n=NC*NR
    def sn(r,c): return (NR-1-r)*NC+c+1
    bad=0
    for i,pg in enumerate(rd.pages[1:]):
        r,c=divmod(i,NC); k=sn(r,c)
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
    p,_,_,_=load_svg(tf)
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

print("\n9. standalone build")
r=subprocess.run([sys.executable, os.path.join(HERE,'build_standalone.py'),'--check'],
                 capture_output=True, text=True)
ck("svgtile-standalone.py matches modules", r.returncode==0,
   "" if r.returncode==0 else "run: python3 build_standalone.py")

print("\n"+("ALL TESTS PASSED" if not fails else f"FAILED: {fails}"))
sys.exit(1 if fails else 0)
