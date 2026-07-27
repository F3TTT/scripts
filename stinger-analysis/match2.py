import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

tmpl_path, full_path = sys.argv[1], sys.argv[2]
thr = float(sys.argv[3]) if len(sys.argv)>3 else 0.25

NPER=2048; HOP=512
def spec(x, sr):
    f,t,Z = stft(x, fs=sr, nperseg=NPER, noverlap=NPER-HOP, window="hann", padded=False, boundary=None)
    S = (20*np.log10(np.abs(Z)+1e-9)).astype(np.float32)
    return f,t,S

def norm(M):
    M = M - M.mean(axis=0, keepdims=True)
    n = np.linalg.norm(M, axis=0, keepdims=True)+1e-9
    return (M/n).astype(np.float32)

# template
sr, xt = wavfile.read(tmpl_path)
if xt.ndim>1: xt=xt.mean(axis=1)
xt=xt.astype(np.float32); xt/=(np.abs(xt).max()+1e-9)
f,_,T = spec(xt, sr)
band = np.where((f>=2000)&(f<=9000))[0]
Tn = norm(T[band]); nT=Tn.shape[1]

# full, read once
srf, xf = wavfile.read(full_path)
if xf.ndim>1: xf=xf.mean(axis=1)
xf=xf.astype(np.float32); xf/=(np.abs(xf).max()+1e-9)
N=len(xf)
dt = HOP/srf

CH = 600*srf          # 10-min chunks
OV = int(3*srf)       # overlap
sims=[]; times=[]
pos=0
while pos < N:
    seg = xf[pos:pos+CH+OV]
    if len(seg) < NPER: break
    _,ts,S = spec(seg, srf)
    Fn = norm(S[band])
    L = Fn.shape[1]-nT+1
    if L>0:
        s = np.zeros(L, dtype=np.float32)
        for j in range(nT):
            s += Tn[:,j] @ Fn[:, j:j+L]
        s/=nT
        base = pos/srf
        for k in range(L):
            # only keep first CH worth (avoid double-count in overlap)
            if ts[k] < 600+ (3 if pos+CH<N else 999):
                sims.append(s[k]); times.append(base+ts[k])
    pos += CH
    del S, Fn

sims=np.array(sims); times=np.array(times)
# peak pick: sort desc, min 3s apart
order=np.argsort(sims)[::-1]
taken=[]; cand=[]
for idx in order:
    if sims[idx]<thr: break
    ts=times[idx]
    if any(abs(ts-o)<3.0 for o in taken): continue
    taken.append(ts); cand.append((ts,float(sims[idx])))
cand.sort()

markers=[12*60+33,29*60+41,32*60+13,39*60+10,81*60+8,89*60+42,91*60+52,99*60+50,115*60+56]
print(f"template {nT*dt:.2f}s  full {N/srf/60:.1f}min  dt={dt*1000:.0f}ms  thr={thr}")
print(f"{'#':>2} {'time':>8} {'sim':>5}  note")
for n,(ts,sv) in enumerate(cand,1):
    mm=int(ts//60); ss=ts%60
    mk=min(markers,key=lambda m:abs(ts-m)); d=abs(ts-mk)
    note=f"~existing ID {int(mk//60)}:{int(mk%60):02d} (d{d:.0f}s)" if d<8 else "NEW (no marker)"
    if abs(ts-(41*60+9))<7: note+="  <<<< user's 41:09"
    print(f"{n:>2} {mm:02d}:{ss:05.2f} {sv:5.2f}  {note}")
print(f"\ntotal>={thr}: {len(cand)}   existing markers: {len(markers)}")
# also print sim value specifically near 41:09 and each marker
def peaknear(target,w=6):
    m=(times>target-w)&(times<target+w)
    return (sims[m].max() if m.any() else float('nan'))
print("\nsim at each existing ID marker + 41:09:")
for mk in markers:
    print(f"  {int(mk//60):02d}:{int(mk%60):02d}  peaksim={peaknear(mk):.2f}")
print(f"  41:09  peaksim={peaknear(41*60+9):.2f}")
