import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft
from scipy.ndimage import median_filter

full_path = sys.argv[1]
MINPROM = float(sys.argv[2]) if len(sys.argv)>2 else 15.0   # dB above local bg
MINDUR  = float(sys.argv[3]) if len(sys.argv)>3 else 0.5    # seconds

NPER=8192; HOP=2048   # fine freq res for tones (~2.7Hz), 93ms hop
srf, xf = wavfile.read(full_path)
if xf.ndim>1: xf=xf.mean(axis=1)
xf=xf.astype(np.float32); xf/=(np.abs(xf).max()+1e-9)
N=len(xf); dt=HOP/srf

fbins = np.fft.rfftfreq(NPER, 1/srf)
band = np.where((fbins>=2500)&(fbins<=10000))[0]
nmed = int(120/(fbins[1]-fbins[0]))  # +/-120 Hz local background

# accumulate per-bin "tonal" boolean over whole file, chunked
CH=600*srf; OV=NPER
all_tonal=[]; all_prom=[]; all_t=[]
pos=0
while pos<N:
    seg=xf[pos:pos+CH+OV]
    if len(seg)<NPER: break
    f,t,Z=stft(seg,fs=srf,nperseg=NPER,noverlap=NPER-HOP,window="hann",padded=False,boundary=None)
    Sd=(20*np.log10(np.abs(Z)+1e-9)).astype(np.float32)
    Sb=Sd[band]
    bg=median_filter(Sb,size=(2*nmed+1,1))
    prom=Sb-bg
    # local freq maximum
    ismax=np.zeros_like(prom,dtype=bool)
    ismax[1:-1,:]=(Sb[1:-1,:]>Sb[:-2,:])&(Sb[1:-1,:]>Sb[2:,:])
    tonal=(prom>MINPROM)&ismax
    keep = t< (600 if pos+CH<N else 1e9)
    all_tonal.append(tonal[:,keep]); all_prom.append(prom[:,keep])
    all_t.append(pos/srf+t[keep])
    pos+=CH
    del Sd,Sb,bg,prom
T=np.concatenate(all_tonal,axis=1)
P=np.concatenate(all_prom,axis=1)
tv=np.concatenate(all_t)
fb=fbins[band]
minf=max(2,int(MINDUR/dt))

# find sustained runs: same bin (+-1) tonal across >=minf consecutive frames
events=[]
nb=T.shape[0]
for b in range(1,nb-1):
    col=T[b,:]|T[b-1,:]|T[b+1,:]
    i=0
    while i<len(col):
        if col[i]:
            j=i
            while j<len(col) and col[j]: j+=1
            if j-i>=minf:
                seg_prom=P[b,i:j].mean()
                events.append((tv[i], fb[b], (j-i)*dt, seg_prom))
            i=j
        else: i+=1
# dedup nearby (same time within 0.4s and freq within 200Hz -> keep max prom)
events.sort(key=lambda e:-e[3])
kept=[]
for e in events:
    if any(abs(e[0]-k[0])<0.6 and abs(e[1]-k[1])<250 for k in kept): continue
    kept.append(e)
kept.sort()
markers=[12*60+33,29*60+41,32*60+13,39*60+10,81*60+8,89*60+42,91*60+52,99*60+50,115*60+56]
print(f"sustained pure tones: prom>{MINPROM}dB dur>{MINDUR}s  band 2.5-10kHz  dt={dt*1000:.0f}ms")
print(f"{'time':>8} {'freqHz':>7} {'dur':>5} {'prom':>5}  note")
for ts,fq,du,pr in kept:
    mm=int(ts//60); ss=ts%60
    mk=min(markers,key=lambda m:abs(ts-m)); d=abs(ts-mk)
    note=f"~ID {int(mk//60)}:{int(mk%60):02d}" if d<8 else ""
    if abs(ts-(41*60+9))<8: note+="  <<<< 41:09"
    print(f"{mm:02d}:{ss:05.2f} {fq:7.0f} {du:5.2f} {pr:5.1f}  {note}")
print(f"\ntotal sustained tones: {len(kept)}")
