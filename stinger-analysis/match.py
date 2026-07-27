import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

tmpl_path, full_path = sys.argv[1], sys.argv[2]

def logspec(path):
    sr, x = wavfile.read(path)
    if x.ndim>1: x = x.mean(axis=1)
    x = x.astype(np.float64); x/=(np.abs(x).max()+1e-9)
    nper=2048; hop=512
    f,t,Z = stft(x, fs=sr, nperseg=nper, noverlap=nper-hop, window="hann")
    S = 20*np.log10(np.abs(Z)+1e-9)
    return f,t,S,sr

f,tt,T,sr = logspec(tmpl_path)
_,tf,F,_ = logspec(full_path)

# restrict to the sting band (2-9 kHz) where the tones live
band = np.where((f>=2000)&(f<=9000))[0]
T=T[band]; F=F[band]

# per-frame normalize (zero-mean, unit-norm) so we match SHAPE not loudness
def norm(M):
    M = M - M.mean(axis=0, keepdims=True)
    n = np.linalg.norm(M, axis=0, keepdims=True)+1e-9
    return M/n
Tn = norm(T)     # band x Ftmpl
Fn = norm(F)     # band x Ffull

nT = Tn.shape[1]
nF = Fn.shape[1]
# similarity(k) = (1/nT) sum_j <Tn[:,j], Fn[:,k+j]>  -> average cosine over template frames
# compute via accumulation over template frames
sim = np.zeros(nF-nT+1)
for j in range(nT):
    # dot of Tn[:,j] with Fn[:, j : j+len(sim)]
    sim += Tn[:,j] @ Fn[:, j:j+len(sim)]
sim /= nT

dt = tf[1]-tf[0]
# find peaks: local maxima above threshold, min 3s apart
thr = float(sys.argv[3]) if len(sys.argv)>3 else 0.30
cand = []
i=0
order = np.argsort(sim)[::-1]
taken=[]
for idx in order:
    if sim[idx] < thr: break
    tsec = tf[idx]  # start of template alignment
    if any(abs(tsec-o)<3.0 for o in taken): continue
    taken.append(tsec)
    cand.append((tsec, sim[idx]))
cand.sort()
print(f"template frames={nT} ({nT*dt:.2f}s)  full frames={nF}  dt={dt*1000:.0f}ms  thr={thr}")
print(f"{'#':>2} {'abs_time':>9} {'sim':>5}")
markers=[12*60+33,29*60+41,32*60+13,39*60+10,81*60+8,89*60+42,91*60+52,99*60+50,115*60+56]
for n,(ts,sv) in enumerate(cand,1):
    mm=int(ts//60); ss=ts%60
    near = min((abs(ts-mk) for mk in markers), default=999)
    tag = f"  ~ID@{int(min(markers,key=lambda mk:abs(ts-mk))//60)}:{int(min(markers,key=lambda mk:abs(ts-mk))%60):02d} (Δ{near:.0f}s)" if near<8 else "  *** no existing marker"
    near4109 = "  <<< 41:09 !!!" if abs(ts-(41*60+9))<6 else ""
    print(f"{n:>2} {mm:02d}:{ss:05.2f} {sv:5.2f}{tag}{near4109}")
print(f"\ntotal candidates >= {thr}: {len(cand)}   (existing ID markers: {len(markers)})")
