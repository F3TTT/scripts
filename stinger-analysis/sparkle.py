import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

# Detect "sparkly electronic" transitions: a SUSTAINED bloom of high-band
# (9-16 kHz) shimmer that rises well above the slow local baseline, lasting
# longer than an impulsive percussion tick.
full_path = sys.argv[1]
RISE = float(sys.argv[2]) if len(sys.argv)>2 else 6.0   # dB above local baseline
MINDUR = float(sys.argv[3]) if len(sys.argv)>3 else 0.35
MAXDUR = float(sys.argv[4]) if len(sys.argv)>4 else 4.0

sr, x = wavfile.read(full_path)
if x.ndim>1: x=x.mean(axis=1)
x=x.astype(np.float32); x/=(np.abs(x).max()+1e-9)
NPER=2048; HOP=512
f,t,Z=stft(x,fs=sr,nperseg=NPER,noverlap=NPER-HOP,window="hann",padded=False,boundary=None)
S=np.abs(Z).astype(np.float32)**2
dt=HOP/sr

hi=np.where((f>=9000)&(f<=16000))[0]
mid=np.where((f>=300)&(f<=4000))[0]
hi_e=S[hi].sum(axis=0)
mid_e=S[mid].sum(axis=0)
# brightness envelope in dB: high band vs mid band (sparkle = high relative brightness)
bright=10*np.log10((hi_e+1e-9)/(mid_e+1e-9))
# also absolute high-band level in dB
hidb=10*np.log10(hi_e+1e-9)

# slow local baseline of brightness (median over +-8s)
from scipy.ndimage import median_filter
w=int(8/dt)
base=median_filter(bright,size=2*w+1)
excess=bright-base   # dB above local baseline

minf=max(2,int(MINDUR/dt)); maxf=int(MAXDUR/dt)
# find runs where excess>RISE, length in [minf,maxf]
events=[]
i=0
above=excess>RISE
while i<len(above):
    if above[i]:
        j=i
        while j<len(above) and above[j]: j+=1
        L=j-i
        if minf<=L<=maxf:
            k=i+int(np.argmax(excess[i:j]))
            events.append((t[k], L*dt, excess[i:j].max(), hidb[i:j].max()))
        i=j
    else: i+=1

markers=[12*60+33,29*60+41,32*60+13,39*60+10,81*60+8,89*60+42,91*60+52,99*60+50,115*60+56]
events.sort(key=lambda e:-e[2])
print(f"SPARKLE candidates: high-band(9-16k) brightness >+{RISE}dB over local base, dur {MINDUR}-{MAXDUR}s")
print(f"{'time':>8} {'dur':>5} {'exc_dB':>6} {'hi_dB':>6}  note")
shown=[]
for tk,du,exc,hd in events:
    if any(abs(tk-s)<2 for s in shown): continue
    shown.append(tk)
    mm=int(tk//60); ss=tk%60
    mk=min(markers,key=lambda m:abs(tk-m)); d=abs(tk-mk)
    note=f"~ID {int(mk//60)}:{int(mk%60):02d}(d{d:.0f})" if d<8 else ""
    if abs(tk-(41*60+9))<8: note+="  <<<< 41:09"
    print(f"{mm:02d}:{ss:05.2f} {du:5.2f} {exc:6.1f} {hd:6.1f}  {note}")
    if len(shown)>=60: break
print(f"\ntotal sparkle candidates: {len(events)}")
# brightness excess specifically at 41:09 and each marker
def near(tt,wsec=8):
    m=(t>tt-wsec)&(t<tt+wsec)
    return excess[m].max() if m.any() else float('nan')
print("\nbrightness-excess peak near each point:")
for mk in markers: print(f"  {int(mk//60):02d}:{int(mk%60):02d}  +{near(mk):.1f}dB")
print(f"  41:09  +{near(41*60+9):.1f}dB")
