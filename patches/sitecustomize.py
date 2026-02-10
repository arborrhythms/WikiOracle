# Patch for PyTorch 2.9.1 TF32 API conflict on pre-Ampere GPUs (e.g. T4).
# NanoChat sets torch.backends.fp32_precision = "tf32" (new API), but
# torch.compile's inductor reads torch.backends.cuda.matmul.allow_tf32
# (legacy API), which crashes due to mixed API state.
# This patch syncs the legacy API after NanoChat's init to prevent the crash.

import torch.backends.cuda

_orig_getattr = torch.backends.cuda.CublasModule.__getattr__

def _patched_getattr(self, name):
    if name == "allow_tf32":
        try:
            return _orig_getattr(self, name)
        except RuntimeError:
            return False
    return _orig_getattr(self, name)

torch.backends.cuda.CublasModule.__getattr__ = _patched_getattr
