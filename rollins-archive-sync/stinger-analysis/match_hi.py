import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

# Matched filter on the 11-16 kHz band only (speech/words don't reach here, so
# the stinger's glitter pattern is relatively clean even in a masked instance).
full_path=sys.argv[1]
t_start=float(sys.argv[2])   # template start (abs s)
t_len=float(sys.argv[3])     # template length (s)
thr=float(sys.argv[4]) if len(sys.argv)>4 else 0.4

NPER=2048; HOP=512
LO,HI=11000,16500

sr,x=wavfile.read(full_path)
if x.ndim>1: x=x.mean(axis=1)
x=x.astype(np.float32); x/=(np.abs(x).max()+1e-9)
dt=HOP/sr
f=np.fft.rfftfreq(NPER,1/sr)
band=np.where((f>=LO)&(f<=HI))[0]

def bandspec(seg):
    _,t,Z=stft(seg,fs=sr,nperseg=NPER,noverlap=NPER-HOP,window="hann",padded=False,boundary=None)
    S=(20*np.log10(np.abs(Z[band])+1e-9)).astype(np.float32)
    return t,S
def norm(M):
    M=M-M.mean(0,keepdims=True)
    return (M/(np.linalg.norm(M,axis=0,keepdims=True)+1e-9)).astype(np.float32)

# template
a=int(t_start*sr); b=int((t_start+t_len)*sr)
_,T=bandspec(x[a:b]); Tn=norm(T); nT=Tn.shape[1]

# slide over full file in chunks
CH=600*sr; OV=int((t_len+1)*sr)
sims=[]; times=[]
pos=0
while pos<len(x):
    seg=x[pos:pos+CH+OV]
    if len(seg)<NPER: break
    t,S=bandspec(seg)
    Fn=norm(S); L=Fn.shape[1]-nT+1
    if L>0:
        s=np.zeros(L,dtype=np.float32)
        for j in range(nT):
            s+=Tn[:,j]@Fn[:,j:j+L]
        s/=nT
        keep=t[:L]<(600 if pos+CH<len(x) else 1e9)
        sims.append(s[keep]); times.append(pos/sr+t[:L][keep])
    pos+=CH
    del S,Fn
sims=np.concatenate(sims); times=np.concatenate(times)

markers=[12*60+33,29*60+41,32*60+13,39*60+10,81*60+8,89*60+42,91*60+52,99*60+50,115*60+56]
target=80*60+41
order=np.argsort(sims)[::-1]; taken=[]; cand=[]
for i in order:
    if sims[i]<thr: break
    ts=times[i]
    if any(abs(ts-o)<4 for o in taken): continue
    taken.append(ts); cand.append((ts,float(sims[i])))
cand.sort()
print(f"11-16kHz matched filter | template {t_start:.1f}+{t_len:.1f}s ({nT} frames) | thr {thr}")
print(f"{'time':>8} {'sim':>5}  note")
for ts,sv in cand:
    mm=int(ts//60); ss=ts%60
    mk=min(markers,key=lambda m:abs(ts-m)); d=abs(ts-mk)
    note=f"~ID {int(mk//60)}:{int(mk%60):02d}(d{d:.0f})" if d<12 else ""
    if abs(ts-target)<5: note+="  <<<< STINGER"
    print(f"{mm:02d}:{ss:05.2f} {sv:5.2f}  {note}")
print(f"\ncandidates>= {thr}: {len(cand)}")
# self and neighbours
def peak(tt,w=5):
    m=(times>tt-w)&(times<tt+w); return sims[m].max() if m.any() else float('nan')
print(f"sim at stinger 80:41 = {peak(target):.2f}")
print("sim at each existing ID marker:")
for mk in markers: print(f"  {int(mk//60):02d}:{int(mk%60):02d} = {peak(mk):.2f}")
