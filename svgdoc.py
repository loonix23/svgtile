"""SVG -> polylines in CENTIMETRES, with correct real-world unit resolution."""
import re, math
from lxml import etree
from svgpath import parse_path

SVG_NS='{http://www.w3.org/2000/svg}'
# CSS absolute units -> cm (SVG/CSS reference: 96 user units = 1 inch)
UNIT_CM = {'mm':0.1,'cm':1.0,'in':2.54,'pt':2.54/72,'pc':2.54/6,
           'px':2.54/96,'q':0.025,'':None}
LEN=re.compile(r'^\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*$')

def parse_len(s, dpi=96.0):
    """Return (value_in_cm or None if unitless/%, raw_value, unit)."""
    if s is None: return (None,None,None)
    m=LEN.match(str(s))
    if not m: return (None,None,None)
    v=float(m.group(1)); u=m.group(2).lower()
    if u=='%': return (None,v,'%')
    if u=='' : return (None,v,'')
    if u=='px': return (v*2.54/dpi, v, 'px')
    f=UNIT_CM.get(u)
    return ((v*f if f else None), v, u)

# ---------------- transforms ----------------
def mat_mul(a,b):
    return (a[0]*b[0]+a[2]*b[1], a[1]*b[0]+a[3]*b[1],
            a[0]*b[2]+a[2]*b[3], a[1]*b[2]+a[3]*b[3],
            a[0]*b[4]+a[2]*b[5]+a[4], a[1]*b[4]+a[3]*b[5]+a[5])
def mat_apply(m,p): return (m[0]*p[0]+m[2]*p[1]+m[4], m[1]*p[0]+m[3]*p[1]+m[5])
IDENT=(1,0,0,1,0,0)

TF=re.compile(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)')
def parse_transform(s):
    if not s: return IDENT
    m=IDENT
    for name,args in TF.findall(s):
        a=[float(x) for x in re.findall(r'[-+]?[\d.]+(?:[eE][-+]?\d+)?',args)]
        if name=='matrix' and len(a)==6: t=tuple(a)
        elif name=='translate': t=(1,0,0,1,a[0], a[1] if len(a)>1 else 0)
        elif name=='scale':     sx=a[0]; sy=a[1] if len(a)>1 else sx; t=(sx,0,0,sy,0,0)
        elif name=='rotate':
            r=math.radians(a[0]); c,s2=math.cos(r),math.sin(r)
            t=(c,s2,-s2,c,0,0)
            if len(a)>=3:
                t=mat_mul((1,0,0,1,a[1],a[2]), mat_mul(t,(1,0,0,1,-a[1],-a[2])))
        elif name=='skewX': t=(1,0,math.tan(math.radians(a[0])),1,0,0)
        elif name=='skewY': t=(1,math.tan(math.radians(a[0])),0,1,0,0)
        else: t=IDENT
        m=mat_mul(m,t)
    return m

def _f(el,name,dflt=0.0):
    v=el.get(name)
    if v is None: return dflt
    m=LEN.match(v)
    return float(m.group(1)) if m else dflt

def _shape_points(el, steps):
    tag=etree.QName(el).localname
    if tag=='path':
        d=el.get('d')
        return parse_path(d,steps) if d else []
    if tag=='line':
        return [([(_f(el,'x1'),_f(el,'y1')),(_f(el,'x2'),_f(el,'y2'))],False)]
    if tag in ('polyline','polygon'):
        nums=[float(x) for x in re.findall(r'[-+]?[\d.]+(?:[eE][-+]?\d+)?',el.get('points',''))]
        pts=list(zip(nums[0::2],nums[1::2]))
        if not pts: return []
        if tag=='polygon': pts=pts+[pts[0]]
        return [(pts, tag=='polygon')]
    if tag=='rect':
        x,y,w,h=_f(el,'x'),_f(el,'y'),_f(el,'width'),_f(el,'height')
        rx,ry=_f(el,'rx'),_f(el,'ry')
        if rx or ry:
            rx=rx or ry; ry=ry or rx; rx=min(rx,w/2); ry=min(ry,h/2)
            d=(f"M{x+rx},{y} H{x+w-rx} A{rx},{ry} 0 0 1 {x+w},{y+ry} V{y+h-ry} "
               f"A{rx},{ry} 0 0 1 {x+w-rx},{y+h} H{x+rx} A{rx},{ry} 0 0 1 {x},{y+h-ry} "
               f"V{y+ry} A{rx},{ry} 0 0 1 {x+rx},{y} Z")
            return parse_path(d,steps)
        return [([(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)],True)]
    if tag in ('circle','ellipse'):
        cx,cy=_f(el,'cx'),_f(el,'cy')
        r =_f(el,'r'); rx=_f(el,'rx') or r; ry=_f(el,'ry') or r
        if rx<=0 or ry<=0: return []
        n=max(24,steps*2)
        pts=[(cx+rx*math.cos(2*math.pi*i/n), cy+ry*math.sin(2*math.pi*i/n)) for i in range(n+1)]
        return [(pts,True)]
    return []

SKIP={'defs','metadata','title','desc','clipPath','mask','marker','symbol','pattern','filter'}

def _style(el, inherited):
    st=dict(inherited)
    css=el.get('style')
    if css:
        for kv in css.split(';'):
            if ':' in kv:
                k,v=kv.split(':',1); st[k.strip()]=v.strip()
    for k in ('stroke','stroke-width','fill','stroke-dasharray'):
        if el.get(k) is not None: st[k]=el.get(k)
    return st

def load_svg(path, dpi=96.0, curve_steps=24, scale_override=None):
    """Return (polylines_in_cm, width_cm, height_cm, info)."""
    tree=etree.parse(path)
    root=tree.getroot()
    wcm,wraw,wu = parse_len(root.get('width'), dpi)
    hcm,hraw,hu = parse_len(root.get('height'), dpi)
    vb=root.get('viewBox')
    if vb:
        n=[float(x) for x in re.findall(r'[-+]?[\d.]+(?:[eE][-+]?\d+)?',vb)]
        vbx,vby,vbw,vbh=n[:4]
    else:
        vbx=vby=0.0; vbw=wraw or 100.0; vbh=hraw or 100.0

    # user units -> cm
    if scale_override:
        k_x=k_y=scale_override
        basis=f"manual override {scale_override} cm/unit"
    elif wcm and hcm and vbw and vbh:
        k_x=wcm/vbw; k_y=hcm/vbh
        basis=f"width/height ({root.get('width')} x {root.get('height')}) vs viewBox"
    elif wcm and vbw:
        k_x=k_y=wcm/vbw; basis="width vs viewBox"
    else:
        k_x=k_y=2.54/dpi
        basis=f"no physical size in SVG -> assumed {dpi} user-units/inch"

    polys=[]
    def walk(el, mat, st):
        tag=etree.QName(el).localname
        if tag in SKIP: return
        mat=mat_mul(mat, parse_transform(el.get('transform')))
        st=_style(el,st)
        if tag in ('g','svg','a'):
            for ch in el: walk(ch, mat, st)
            return
        for pts,closed in _shape_points(el,curve_steps):
            tp=[mat_apply(mat,p) for p in pts]
            polys.append(dict(pts=tp, closed=closed,
                              width=st.get('stroke-width'),
                              dash=st.get('stroke-dasharray'),
                              stroke=st.get('stroke'), fill=st.get('fill')))
    walk(root, IDENT, {})

    # viewBox origin -> 0, then scale to cm
    out=[]
    for p in polys:
        p['pts']=[((x-vbx)*k_x, (y-vby)*k_y) for x,y in p['pts']]
        out.append(p)
    W = wcm if wcm else vbw*k_x
    H = hcm if hcm else vbh*k_y
    info=dict(basis=basis, k_x=k_x, k_y=k_y, viewbox=(vbx,vby,vbw,vbh),
              nonuniform=abs(k_x-k_y)>1e-9)
    return out, W, H, info
