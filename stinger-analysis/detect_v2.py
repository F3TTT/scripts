import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft
from scipy.ndimage import median_filter, uniform_filter1d

# Sparkle-stinger detector v2.
# Signature: a SUSTAINED shimmer with strong VERY-high-band (11-16 kHz) energy,
# well above the slow local baseline. Speech dies by ~8 kHz; music up there is
# only impulsive cymbal ticks. The stinger sustains a granular high bloom.
full_path = sys.argv[1]
RISE   = float(sys.argv[2]) if len(sys.argv)>2 else 8.0   # dB above local baseline
MINDUR = float(sys.argv[3]) if len(sys.argv)>3 else 0.6
MAXDUR = float(sys.argv[4]) if len(sys.argv)>4 else 3.5

sr, x = wavfile.read(full_path)   # NB: needs 44.1k source for 11-16 kHz
if x.ndim>1: x=x.mean(axis=1)
x=x.astype(np.float32); x/=(np.abs(x).max()+1e-9)
NPER=2048; HOP=512
dt=HOP/sr
vhi=None
sims_t=[]; excess=[]; vhidb_all=[]
# process in chunks to bound memory
CH=600*sr; OV=NPER
pos=0
ex_list=[]; t_list=[]; vh_list=[]
while pos < len(x):
    seg=x[pos:pos+CH+OV]
    if len(seg)<NPER: break
    f,t,Z=stft(seg,fs=sr,nperseg=NPER,noverlap=NPER-HOP,window="hann",padded=False,boundary=None)
    S=np.abs(Z).astype(np.float32)**2
    vhi_i=np.where((f>=11000)&(f<=16000))[0]
    mid_i=np.where((f>=300)&(f<=3000))[0]
    bright=10*np.log10((S[vhi_i].sum(0)+1e-9)/(S[mid_i].sum(0)+1e-9))
    vhidb=10*np.log10(S[vhi_i].sum(0)+1e-9)
    keep=t<(600 if pos+CH<len(x) else 1e9)
    ex_list.append(bright[keep]); t_list.append(pos/sr+t[keep]); vh_list.append(vhidb[keep])
    pos+=CH
    del S
bright=np.concatenate(ex_list); tv=np.concatenate(t_list); vhidb=np.concatenate(vh_list)
# smooth brightness a touch (stinger sustains; single ticks shouldn't win)
bright_s=uniform_filter1d(bright, size=max(1,int(0.12/dt)))
w=int(10/dt)
base=median_filter(bright_s, size=2*w+1)
exc=bright_s-base

minf=max(2,int(MINDUR/dt)); maxf=int(MAXDUR/dt)
above=exc>RISE
events=[]; i=0
while i<len(above):
    if above[i]:
        j=i
        while j<len(above) and above[j]: j+=1
        L=j-i
        if minf<=L<=maxf:
            k=i+int(np.argmax(exc[i:j]))
            events.append((tv[i], L*dt, exc[i:j].mean(), exc[i:j].max(), vhidb[i:j].max()))
        i=j
    else: i+=1

markers=[12*60+33,29*60+41,32*60+13,39*60+10,81*60+8,89*60+42,91*60+52,99*60+50,115*60+56]
target=80*60+41
events.sort(key=lambda e:-(e[2]*e[1]))   # rank by mean-excess * duration
print(f"detector v2: 11-16kHz brightness > +{RISE}dB over local base, dur {MINDUR}-{MAXDUR}s")
print(f"ranked by (mean_excess x duration).  {len(events)} raw candidates")
print(f"{'rank':>4} {'time':>8} {'dur':>4} {'meanEx':>6} {'maxEx':>6}  note")
for r,(t0,du,me,mx,vh) in enumerate(events[:40],1):
    mm=int(t0//60); ss=t0%60
    mk=min(markers,key=lambda m:abs(t0-m)); d=abs(t0-mk)
    note=f"~ID {int(mk//60)}:{int(mk%60):02d}(d{d:.0f})" if d<10 else ""
    if abs(t0-target)<6: note+="  <<<< THE STINGER (80:41)"
    print(f"{r:>4} {mm:02d}:{ss:05.2f} {du:4.1f} {me:6.1f} {mx:6.1f}  {note}")
# where does the stinger rank?
for r,(t0,du,me,mx,vh) in enumerate(events,1):
    if abs(t0-target)<6:
        print(f"\n>>> stinger at {int(t0//60)}:{t0%60:05.2f} ranks #{r} of {len(events)} (dur {du:.1f}s, meanEx {me:.1f}dB)")
        break
else:
    print(f"\n>>> stinger NOT among candidates at thr {RISE}dB")
