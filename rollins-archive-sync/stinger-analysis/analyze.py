import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft

path = sys.argv[1]
win_start_s = float(sys.argv[2])  # absolute file time of clip start
sr, x = wavfile.read(path)
if x.ndim > 1:
    x = x.mean(axis=1)
x = x.astype(np.float64)
x /= (np.abs(x).max() + 1e-9)

# High-res STFT
nper = 4096
f, t, Z = stft(x, fs=sr, nperseg=nper, noverlap=nper*3//4, window="hann")
S = np.abs(Z)  # freq x time
# Convert to dB
Sd = 20*np.log10(S + 1e-9)

def band_idx(lo, hi):
    return np.where((f >= lo) & (f < hi))[0]

# For each time frame, find the strongest narrowband peak above 2 kHz and how much
# it stands above the median of the whole frame (a "tonal prominence" score).
hi_idx = band_idx(2000, 16000)
frame_med = np.median(Sd, axis=0)
peak_val = Sd[hi_idx, :].max(axis=0)
peak_frq = f[hi_idx][Sd[hi_idx, :].argmax(axis=0)]
prominence = peak_val - frame_med   # dB above frame median

# Also: high-band energy ratio (3-8kHz vs total) as a transient sting indicator
hb = band_idx(2500, 9000)
lb = band_idx(0, 2500)
hb_e = (S[hb, :]**2).sum(axis=0)
lb_e = (S[lb, :]**2).sum(axis=0)
ratio = 10*np.log10((hb_e + 1e-12) / (lb_e + 1e-12))

# Report the frames with highest tonal prominence in the high band
order = np.argsort(prominence)[::-1]
print(f"clip start = {win_start_s:.1f}s (abs)  sr={sr}  dur={len(x)/sr:.1f}s")
print(f"{'abs_time':>9} {'rel':>6} {'peakHz':>8} {'promdB':>7} {'hb/lb dB':>8}")
seen=[]
for i in order:
    tt = t[i]
    if any(abs(tt-s) < 1.0 for s in seen):
        continue
    seen.append(tt)
    abst = win_start_s + tt
    mm=int(abst//60); ss=abst%60
    print(f"{mm:02d}:{ss:05.2f} {tt:6.2f} {peak_frq[i]:8.0f} {prominence[i]:7.1f} {ratio[i]:8.1f}")
    if len(seen) >= 15:
        break
