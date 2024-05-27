# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/hits_04_service.ipynb.

# %% auto 0
__all__ = ['DEF_FMT', 'split_audio', 'Config', 'apply_transforms', 'predict', 'stream_loop', 'init_logger', 'main']

# %% ../../nbs/hits_04_service.ipynb 1
import onnxruntime, requests, math, soundfile as sf
from fastprogress import progress_bar
from collections import deque
import librosa, numpy as np, logging as l, time
from dataclasses import dataclass
from pathlib import Path
from fastcore.all import ifnone, call_parse
from datetime import date

# %% ../../nbs/hits_04_service.ipynb 2
def split_audio(arr, w_size, stride):
    n_frames = (arr.shape[0] - w_size)//stride + 1
    strides = (stride*arr.dtype.itemsize, arr.dtype.itemsize)
    return np.lib.stride_tricks.as_strided(arr, shape=(n_frames, w_size), strides=strides).copy()

# %% ../../nbs/hits_04_service.ipynb 3
@dataclass
class Config:
    sr: int = 16_000
    n_mfcc: int = 64
    window_size_s: float = 1.0
    window_size: int = int(window_size_s*sr)
    stride: int = int(0.7*sr)
    ths: float = 0.7
    buffer_size: int = 25_000
    buffer_stride: int = 15_000
    verbose: bool = False

# %% ../../nbs/hits_04_service.ipynb 4
def apply_transforms(y, cfg: Config):
    # should be the same as `x_tfms`
    n_fft = 400
    win_len = 400
    hop_len = win_len//2
    n_mels = 64
    return librosa.feature.mfcc(
        y=y,
        sr=cfg.sr,
        n_mfcc=cfg.n_mfcc,
        n_fft=n_fft,
        hop_length=hop_len,
        win_length=win_len,
        pad_mode="reflect",
        n_mels=n_mels,
        htk=True,
        norm='slaney')

def predict(audio, model, cfg: Config, pipe=apply_transforms):
    ths = cfg.ths
    window_size=cfg.window_size
    sr = cfg.sr
    
    logit = math.log(ths/(1-ths))
    frames = split_audio(audio, int(3.0*sr), sr)
    res, last_det = [], False
    if cfg.verbose: frames = progress_bar(frames)
    for i,f in enumerate(frames):
        x = pipe(f[window_size:2*window_size], cfg)[None]
        if model(x)[0] >= logit and not last_det:
            l.debug(f"Detected hit at frame {i}. Next frame will be ignored.")
            res.append(f)
            last_det = True
        else: last_det = False
    l.info(f"Detected {len(res)} hits")
    return res


def stream_loop(stream_url, model, out_fldr='./preds', cfg = Config()):
    # init request, buffer and output folder
    out_fldr, tmp = Path(out_fldr), Path('temp.mp3')
    out_fldr.mkdir(exist_ok=True, parents=True)
    buff = deque(maxlen=cfg.buffer_size)

    l.info("Starting stream loop")
    while True:
        r = requests.get(stream_url, stream=True)
        if r.status_code != 200:
            # wait for 30 seconds before retrying
            l.info(f"Got status code {r.status_code}. Retrying in 30 seconds")
            time.sleep(30)
            continue
        l.info(f"Got status code {r.status_code}. Starting reading")  
        total_bytes = 0
        try:
            for block in r.iter_content(4096):
                total_bytes += len(block)
                buff.extend(block)
                
                # when buffer is filled with audio extract, write to file and predict
                if len(buff) == cfg.buffer_size:
                    l.info("Buffer filled, extracting audio")
                    with open(tmp, 'wb') as f:
                        f.write(bytes(buff))
                        # clear buffer for next iteration
                        for _ in range(cfg.buffer_stride): buff.popleft() 
                    l.info("Reading audio from {}")
                    audio, _ = librosa.load(tmp, sr=cfg.sr)
                    l.info(f"Read audio of length {len(audio)}. Predicting")
                    res = predict(audio, model, cfg)
                    for r in res:
                        idx = len(list(out_fldr.iterdir()))
                        fname = out_fldr/f'{idx}.wav'
                        l.debug(f"Writing hit to {fname}")
                        sf.write(fname, r, cfg.sr)
        except requests.exceptions.StreamConsumedError:
            l.info("Stream consumed, retrying")
            continue
        except KeyboardInterrupt: 
            l.info("Got keyboard interrupt, exiting stream loop")
            return
        finally:
            l.info(f"Total bytes read: {total_bytes}")

# %% ../../nbs/hits_04_service.ipynb 5
DEF_FMT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
def init_logger(name: str = None, level=l.INFO, format: str = None, handlers: list = None, logs_dir='./logs'):
    '''Initializes a logger, adds handlers and sets the format. If logs_dir is provided, a file handler is added to the logger.'''
    handlers = ifnone(handlers, [])
    handlers.append(l.StreamHandler())
    if logs_dir: 
        p = Path(logs_dir)/f'{date.today()}.log'
        p.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(l.FileHandler(p)) 
    log_fmt = l.Formatter(ifnone(format, DEF_FMT), datefmt='%Y-%m-%d %H:%M:%S')
    log = l.getLogger(name)
    log.setLevel(level)
    log.handlers.clear()
    for h in handlers: h.setFormatter(log_fmt); log.addHandler(h)

# %% ../../nbs/hits_04_service.ipynb 6
@call_parse
def main(url:str= 'http://localhost:8000/stream', model_path: str = "./model.onnx"):
    init_logger()
    onnx_sess = onnxruntime.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    model = lambda x: onnx_sess.run(None, {"input": x})
    l.info(f"Starting stream loop with model {model_path}")
    l.info(f"Streaming from {url}")
    stream_loop(url, model)
