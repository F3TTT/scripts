import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

path = sys.argv[1]
abs0 = float(sys.argv[2])   # absolute file time of clip start
sr, x = wavfile.read(path)
if x.ndim > 1:
    x = x.mean(axis=1)
x = x.astype(np.float64); x /= (np.abs(x).max()+1e-9)

nper = 8192  # ~5.4 Hz resolution, ~46ms hop at 3/4 overlap
hop = nper//4
f, t, Z = stft(x, fs=sr, nperseg=nper, noverlap=nper-hop, window="hann")
S = np.abs(Z)
Sd = 20*np.log10(S+1e-9)

# A "sustained tone" bin: local spectral peak in freq that stays a peak with
# stable frequency across many consecutive frames. Restrict to 2-9 kHz.
band = np.where((f>=2000)&(f<=9000))[0]

# prominence per bin per frame = value minus local median over +-150Hz
nbins_med = int(150/(f[1]-f[0]))
from scipy.ndimage import median_filter
local_med = median_filter(Sd, size=(2*nbins_med+1,1))
prom = Sd - local_med   # dB above local background

# a bin is "tonal" at frame if prom>10 dB and it's a local freq maximum
tonal = np.zeros_like(prom, dtype=bool)
tonal[1:-1,:] = (prom[1:-1,:]>10) & (Sd[1:-1,:]>Sd[:-2,:]) & (Sd[1:-1,:]>Sd[2:,:])
# mask to band
mask = np.zeros(len(f),dtype=bool); mask[band]=True
tonal &= mask[:,None]

# For each frame, count strongest sustained tones: find runs where SAME freq bin
# (+/-2 bins) is tonal across >= Nframes consecutive frames.
dt = t[1]-t[0]
min_dur = 0.35  # seconds
min_frames = max(2,int(min_dur/dt))

# Build per-bin run lengths
runs = []  # (fbin, start_frame, len)
for b in band:
    col = tonal[b,:]
    i=0
    while i < len(col):
        if col[i]:
            j=i
            while j<len(col) and (tonal[b,j] or tonal[max(0,b-1),j] or tonal[min(len(f)-1,b+1),j]):
                j+=1
            if j-i>=min_frames:
                runs.append((b,i,j-i))
            i=j
        else:
            i+=1

# report sustained tones sorted by time
runs.sort(key=lambda r:r[1])
print(f"clip abs start {abs0:.1f}s  dt={dt*1000:.0f}ms  min_dur={min_dur}s")
print(f"{'abs_time':>9} {'freqHz':>7} {'dur_s':>6} {'meanProm':>8}")
for b,i,L in runs:
    tt = abs0 + t[i]
    mm=int(tt//60); ss=tt%60
    dur=L*dt
    mp=prom[b,i:i+L].mean()
    print(f"{mm:02d}:{ss:05.2f} {f[b]:7.0f} {dur:6.2f} {mp:8.1f}")
