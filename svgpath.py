"""Minimal but correct SVG path parser -> polylines. Handles M L H V C S Q T A Z, abs+rel."""
import math, re

NUM = re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?')
CMD = re.compile(r'([MmLlHhVvCcSsQqTtAaZz])')

def _tok(d):
    out=[]
    for part in CMD.split(d):
        part=part.strip()
        if not part: continue
        if len(part)==1 and part.isalpha(): out.append(part)
        else: out.extend(float(x) for x in NUM.findall(part))
    return out

def _bez3(p0,p1,p2,p3,n):
    return [( (1-t)**3*p0[0]+3*(1-t)**2*t*p1[0]+3*(1-t)*t*t*p2[0]+t**3*p3[0],
              (1-t)**3*p0[1]+3*(1-t)**2*t*p1[1]+3*(1-t)*t*t*p2[1]+t**3*p3[1])
            for t in (i/n for i in range(1,n+1))]

def _bez2(p0,p1,p2,n):
    return [( (1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0],
              (1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1])
            for t in (i/n for i in range(1,n+1))]

def _arc(p0, rx, ry, rot, laf, sf, p1, n):
    """SVG elliptical arc -> points (endpoint parameterisation, per SVG spec F.6)."""
    if p0==p1: return []
    rx,ry = abs(rx),abs(ry)
    if rx==0 or ry==0: return [p1]
    phi = math.radians(rot)
    cs,sn = math.cos(phi), math.sin(phi)
    dx2,dy2 = (p0[0]-p1[0])/2.0, (p0[1]-p1[1])/2.0
    x1p =  cs*dx2 + sn*dy2
    y1p = -sn*dx2 + cs*dy2
    # correct out-of-range radii
    lam = x1p*x1p/(rx*rx) + y1p*y1p/(ry*ry)
    if lam>1:
        s=math.sqrt(lam); rx*=s; ry*=s
    num = rx*rx*ry*ry - rx*rx*y1p*y1p - ry*ry*x1p*x1p
    den = rx*rx*y1p*y1p + ry*ry*x1p*x1p
    co = 0.0 if num<0 or den==0 else math.sqrt(num/den)
    if laf==sf: co=-co
    cxp =  co*rx*y1p/ry
    cyp = -co*ry*x1p/rx
    cx = cs*cxp - sn*cyp + (p0[0]+p1[0])/2.0
    cy = sn*cxp + cs*cyp + (p0[1]+p1[1])/2.0
    def ang(ux,uy,vx,vy):
        d=math.hypot(ux,uy)*math.hypot(vx,vy)
        if d==0: return 0.0
        c=max(-1,min(1,(ux*vx+uy*vy)/d))
        a=math.acos(c)
        return -a if ux*vy-uy*vx<0 else a
    th1 = ang(1,0,(x1p-cxp)/rx,(y1p-cyp)/ry)
    dth = ang((x1p-cxp)/rx,(y1p-cyp)/ry,(-x1p-cxp)/rx,(-y1p-cyp)/ry)
    if not sf and dth>0: dth-=2*math.pi
    elif sf and dth<0: dth+=2*math.pi
    steps=max(2,int(n*abs(dth)/math.pi))
    pts=[]
    for i in range(1,steps+1):
        th=th1+dth*i/steps
        pts.append((cs*rx*math.cos(th)-sn*ry*math.sin(th)+cx,
                    sn*rx*math.cos(th)+cs*ry*math.sin(th)+cy))
    return pts

def parse_path(d, curve_steps=24):
    """Return list of subpaths: (points, closed)."""
    t=_tok(d); i=0
    subs=[]; cur=[]; closed=False
    x=y=0.0; sx=sy=0.0
    pcx=pcy=None   # previous cubic ctrl
    pqx=pqy=None   # previous quad ctrl
    cmd=None
    def flush():
        nonlocal cur,closed
        if len(cur)>1: subs.append((cur,closed))
        cur=[]; closed=False
    while i<len(t):
        if isinstance(t[i],str):
            cmd=t[i]; i+=1
            if cmd in 'Zz':
                if cur:
                    cur.append((sx,sy)); closed=True; flush()
                    x,y=sx,sy
                continue
        rel = cmd.islower(); c=cmd.upper()
        if c=='M':
            nx,ny=t[i],t[i+1]; i+=2
            if rel: nx+=x; ny+=y
            flush(); x,y=nx,ny; sx,sy=x,y; cur=[(x,y)]
            cmd='l' if rel else 'L'
            pcx=pqx=None
        elif c=='L':
            nx,ny=t[i],t[i+1]; i+=2
            if rel: nx+=x; ny+=y
            cur.append((nx,ny)); x,y=nx,ny; pcx=pqx=None
        elif c=='H':
            nx=t[i]; i+=1
            if rel: nx+=x
            cur.append((nx,y)); x=nx; pcx=pqx=None
        elif c=='V':
            ny=t[i]; i+=1
            if rel: ny+=y
            cur.append((x,ny)); y=ny; pcx=pqx=None
        elif c in 'CS':
            if c=='C':
                x1,y1,x2,y2,nx,ny=t[i:i+6]; i+=6
                if rel: x1+=x;y1+=y;x2+=x;y2+=y;nx+=x;ny+=y
            else:
                x2,y2,nx,ny=t[i:i+4]; i+=4
                if rel: x2+=x;y2+=y;nx+=x;ny+=y
                x1,y1 = (2*x-pcx,2*y-pcy) if pcx is not None else (x,y)
            cur+= _bez3((x,y),(x1,y1),(x2,y2),(nx,ny),curve_steps)
            pcx,pcy=x2,y2; pqx=None; x,y=nx,ny
        elif c in 'QT':
            if c=='Q':
                x1,y1,nx,ny=t[i:i+4]; i+=4
                if rel: x1+=x;y1+=y;nx+=x;ny+=y
            else:
                nx,ny=t[i:i+2]; i+=2
                if rel: nx+=x;ny+=y
                x1,y1 = (2*x-pqx,2*y-pqy) if pqx is not None else (x,y)
            cur+= _bez2((x,y),(x1,y1),(nx,ny),curve_steps)
            pqx,pqy=x1,y1; pcx=None; x,y=nx,ny
        elif c=='A':
            rx,ry,rot,laf,sf,nx,ny=t[i:i+7]; i+=7
            if rel: nx+=x; ny+=y
            cur+= _arc((x,y),rx,ry,rot,int(laf),int(sf),(nx,ny),curve_steps)
            x,y=nx,ny; pcx=pqx=None
        else:
            i+=1
    flush()
    return subs
