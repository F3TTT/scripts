import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

path=sys.argv[1]; abs0=float(sys.argv[2])
sr,x=wavfile.read(path)
if x.ndim>1: x=x.mean(axis=1)
x=x.astype(np.float64); x/=(np.abs(x).max()+1e-9)
NPER=2048; HOP=256
f,t,Z=stft(x,fs=sr,nperseg=NPER,noverlap=NPER-HOP,window="hann",padded=False,boundary=None)
S=np.abs(Z)**2
dt=HOP/sr
hi=np.where((f>=4000)&(f<=16000))[0]
lo=np.where((f>=200)&(f<=3000))[0]
hidb=10*np.log10(S[hi].sum(0)+1e-9)
tilt=10*np.log10((S[hi].sum(0)+1e-9)/(S[lo].sum(0)+1e-9))  # brightness tilt
# onset = largest positive jump in brightness tilt over ~0.15s
w=int(0.15/dt)
jump=np.zeros_like(tilt)
jump[w:]=tilt[w:]-tilt[:-w]
k=int(np.argmax(jump))
print(f"clip abs {abs0:.1f}s  dt={dt*1000:.0f}ms")
print(f"strongest brightness onset at abs {abs0+t[k]:.2f}s  ({int((abs0+t[k])//60)}:{(abs0+t[k])%60:05.2f})")
print(f"  brightness tilt jumps {jump[k]:.1f} dB;  tilt before={tilt[k-w]:.1f}dB after={tilt[k]:.1f}dB")
# show tilt curve sampled every 0.25s
print("\ntime(abs)  hi_dB  tilt_dB")
for i in range(0,len(t),int(0.25/dt)):
    ts=abs0+t[i]
    print(f"  {int(ts//60)}:{ts%60:05.2f}  {hidb[i]:6.1f} {tilt[i]:6.1f}")
