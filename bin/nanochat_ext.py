"""WikiOracle extensions mounted onto NanoChat's FastAPI app.

This module defines routes that are added to the NanoChat ``app`` object
**from WikiOracle's codebase** so that NanoChat's own source files remain
unmodified.  The only route so far is ``POST /train`` for online learning.

Usage (as a library)::

    from nanochat_ext import mount_train_route
    mount_train_route(app)

Usage (as entry point — replaces ``python -m scripts.chat_web``)::

    python bin/nanochat_ext.py [--num-gpus N] [--port 8000] ...

Training algorithm — DoT-Annealed Online Training
==================================================

Each ``/train`` call performs a **single optimizer step** with a fresh
AdamW optimizer (no persistent state between calls).  Without momentum
history, AdamW degrades to sign-SGD — simpler, safer, and each
interaction is fully independent so a bad gradient cannot poison future
steps.

**Parameter groups** mirror the production training regime
(``model.setup_optimizer()`` in ``nanochat/nanochat/gpt.py``) but use
AdamW consistently across all groups:

  lm_head (0.0027), wte (0.136), value_embeds (0.136),
  resid_lambdas (0.005), x0_lambdas (0.5), transformer.h (0.02)

**Learning rate modulation** via ``truth_weight`` (0–1 slider):

    lr_effective = lr_base × (truth_weight × |DoT| + (1 - truth_weight))

At truth_weight=0: trains on everything at full LR (vanilla SFT).
At truth_weight=1: DoT fully gates the learning rate.

**Gradient clipping**: ``clip_grad_norm_(params, max_norm)`` prevents
catastrophic single-step weight changes.

**EMA weight anchoring**: After each step, blend weights back toward the
checkpoint anchor to prevent gradual drift:

    p.data.lerp_(anchor, anchor_decay × truth_weight)

**Sigmoid warmup**: Slowly ramp training from 0 to full strength over
the first N interactions, preventing early random updates from
corrupting weights.

See doc/Training.md for the full design.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional

import torch
from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------
class TrainRequest(BaseModel):
    messages: List[dict]        # [{"role": "user"|"assistant", "content": "..."}]
    degree_of_truth: float = 1.0
    device: str = "cpu"         # "auto" | "cpu" | "cuda"
    truth_weight: float = 0.7   # 0.0 = vanilla SFT, 1.0 = full DoT-gated
    warmup_steps: int = 50      # Sigmoid warmup midpoint
    grad_clip: float = 1.0      # Max gradient norm
    anchor_decay: float = 0.001 # EMA blend-back rate toward checkpoint


# ---------------------------------------------------------------------------
# Parameter group learning rates (mirrors model.setup_optimizer())
# ---------------------------------------------------------------------------
# These are the base learning rates from the production training regime
# in nanochat/nanochat/gpt.py:GPT.setup_optimizer().  Online training
# uses AdamW consistently for all groups (see module docstring).
_PARAM_GROUP_LRS = {
    "lm_head":       0.0027,
    "wte":           0.136,
    "value_embeds":  0.136,
    "resid_lambdas": 0.005,
    "x0_lambdas":    0.5,
    "transformer_h": 0.02,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_device(preference: str) -> torch.device:
    """Resolve a device preference string to a ``torch.device``.

    ``"auto"`` probes for CUDA then MPS then falls back to CPU.
    ``"cpu"`` and ``"cuda"`` are taken literally.
    """
    pref = (preference or "cpu").strip().lower()
    if pref == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(pref)


def _sigmoid_warmup(step: int, midpoint: int = 50, k: float = 0.1) -> float:
    """Sigmoid warmup schedule: 0 → 1 over ~2×midpoint steps.

    Returns a value in (0, 1) that ramps up from near-0 to near-1.
    At step=0: ~0.007.  At step=midpoint: 0.5.  At step=2×midpoint: ~0.993.

    Parameters
    ----------
    step : int
        Current online training step count.
    midpoint : int
        The step at which the warmup reaches 50%.
    k : float
        Steepness of the sigmoid curve.
    """
    return 1.0 / (1.0 + math.exp(-k * (step - midpoint)))


def _build_param_groups(model: torch.nn.Module) -> list[dict]:
    """Build AdamW parameter groups matching the production training regime.

    Returns a list of param group dicts with 'params', 'lr', and 'group_name'
    keys.  Each group corresponds to a distinct set of model parameters:

    - lm_head:       output projection weights
    - wte:           token embedding weights
    - value_embeds:  value residual stream embeddings
    - resid_lambdas: per-layer residual scaling scalars
    - x0_lambdas:    skip-connection blending scalars
    - transformer_h: all transformer block matrix parameters

    Parameters not matching any named group are included in transformer_h.
    All groups use AdamW (no Muon) — see module docstring for rationale.
    """
    # Collect named parameter sets by scanning the model
    lm_head_params = []
    wte_params = []
    value_embed_params = []
    resid_lambda_params = []
    x0_lambda_params = []
    transformer_h_params = []

    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        if "lm_head" in name:
            lm_head_params.append(param)
        elif "wte" in name or "embed" in name.lower() and "value" not in name.lower():
            wte_params.append(param)
        elif "value_embed" in name:
            value_embed_params.append(param)
        elif "resid_lambda" in name:
            resid_lambda_params.append(param)
        elif "x0_lambda" in name:
            x0_lambda_params.append(param)
        else:
            # Everything else goes to transformer_h (attention, MLP, norms, etc.)
            transformer_h_params.append(param)

    groups = []
    group_specs = [
        ("lm_head",       lm_head_params),
        ("wte",           wte_params),
        ("value_embeds",  value_embed_params),
        ("resid_lambdas", resid_lambda_params),
        ("x0_lambdas",    x0_lambda_params),
        ("transformer_h", transformer_h_params),
    ]

    for group_name, params in group_specs:
        if params:
            groups.append({
                "params": params,
                "lr": _PARAM_GROUP_LRS.get(group_name, 0.02),
                "group_name": group_name,
            })

    return groups


def mount_train_route(app: FastAPI) -> None:
    """Register ``POST /train`` on *app* (NanoChat's FastAPI instance).

    Also initializes app.state.anchor_params (EMA checkpoint weights)
    and app.state.train_step_count on first call.
    """

    @app.post("/train")
    async def train(request: TrainRequest):
        """Online training endpoint: one forward + backward + optimizer step.

        Input:  ``{"messages": [...], "degree_of_truth": -1.0–1.0,
                   "truth_weight": 0.0–1.0, ...}``

        DoT semantics (range **-1 .. +1**)::

            +1  = the exchange is fully true   → train at full learning rate
             0  = no information / neutral      → skip (nothing to learn)
            -1  = the exchange is fully false   → train at full lr (learning
                  what is *not* true is as valuable as learning what *is* true)

        Learning rate modulation::

            lr_effective = lr_base × (truth_weight × |DoT| + (1 - truth_weight))

        At truth_weight=0: lr_effective = lr_base (full LR regardless of DoT).
        At truth_weight=1: lr_effective = lr_base × |DoT| (DoT gates learning).

        Returns ``{"status": "ok", "loss": float}`` or a no-op dict.
        """
        worker_pool = getattr(app.state, "worker_pool", None)
        if worker_pool is None or len(worker_pool.workers) == 0:
            return {"status": "ok", "loss": None, "message": "no model loaded"}

        dot = max(-1.0, min(1.0, request.degree_of_truth))
        truth_weight = max(0.0, min(1.0, request.truth_weight))

        # DoT ≈ 0 AND truth_weight > 0: no agreement or disagreement signal.
        # Skip when DoT is effectively zero and truth_weight would gate it.
        if truth_weight > 0 and abs(dot) < 1e-6:
            return {"status": "ok", "loss": None, "message": "degree_of_truth ~0, skipped"}

        worker = await worker_pool.acquire_worker()
        try:
            # Tokenize conversation (same format as /chat/completions)
            bos = worker.tokenizer.get_bos_token_id()
            user_start = worker.tokenizer.encode_special("<|user_start|>")
            user_end = worker.tokenizer.encode_special("<|user_end|>")
            assistant_start = worker.tokenizer.encode_special("<|assistant_start|>")
            assistant_end = worker.tokenizer.encode_special("<|assistant_end|>")

            tokens = [bos]
            for message in request.messages:
                role = message.get("role", "")
                content = message.get("content", "")
                if role == "user":
                    tokens.append(user_start)
                    tokens.extend(worker.tokenizer.encode(content))
                    tokens.append(user_end)
                elif role == "assistant":
                    tokens.append(assistant_start)
                    tokens.extend(worker.tokenizer.encode(content))
                    tokens.append(assistant_end)

            if len(tokens) < 2:
                return {"status": "ok", "loss": None, "message": "empty token sequence"}

            model = worker.engine.model

            if not hasattr(model, "parameters"):
                return {"status": "ok", "loss": None, "message": "model not trainable"}

            # ── Initialize EMA anchor weights on first call ──
            if not hasattr(app.state, "anchor_params"):
                app.state.anchor_params = [
                    p.data.clone() for p in model.parameters()
                ]
                app.state.train_step_count = 0
                logger.info("[TRAIN] Initialized EMA anchor weights (%d params)",
                            len(app.state.anchor_params))

            # ── Resolve training device ──
            train_device = _resolve_device(request.device)
            model_device = next(model.parameters()).device
            if model_device != train_device:
                logger.info("[TRAIN] Moving model %s → %s for training step",
                            model_device, train_device)
                model.to(train_device)

            # ── Build parameter groups (fresh optimizer each call) ──
            param_groups = _build_param_groups(model)
            if not param_groups:
                return {"status": "ok", "loss": None, "message": "no trainable params"}

            # ── Compute effective learning rate ──
            # truth_weight modulates how much DoT gates the LR:
            #   tw=0: lr_effective = lr_base (vanilla SFT, no DoT influence)
            #   tw=1: lr_effective = lr_base × |DoT| (fully DoT-gated)
            lr_scale = truth_weight * abs(dot) + (1.0 - truth_weight)

            # Apply sigmoid warmup to prevent early corruption
            step = app.state.train_step_count
            warmup = _sigmoid_warmup(step, midpoint=request.warmup_steps)
            lr_scale *= warmup

            # Scale each group's LR
            for group in param_groups:
                group["lr"] = group["lr"] * lr_scale

            optimizer = torch.optim.AdamW(param_groups)

            # ── Forward + backward + optimizer step ──
            input_ids = torch.tensor([tokens], dtype=torch.long, device=train_device)
            model.train()
            with worker.autocast_ctx:
                logits = model(input_ids[:, :-1])
                targets = input_ids[:, 1:]
                loss = torch.nn.functional.cross_entropy(
                    logits.reshape(-1, logits.size(-1)),
                    targets.reshape(-1),
                )
            optimizer.zero_grad()
            loss.backward()

            # ── Gradient clipping ──
            all_params = [p for g in param_groups for p in g["params"]]
            grad_norm = torch.nn.utils.clip_grad_norm_(
                all_params, max_norm=request.grad_clip
            )

            optimizer.step()
            model.eval()

            # ── EMA weight anchoring (anti-capture) ──
            # Blend weights back toward the checkpoint anchor.
            # anchor_effective = anchor_decay × truth_weight:
            #   tw=0: no anchor pull (weights drift freely)
            #   tw=1: full anchor pull toward checkpoint
            anchor_effective = request.anchor_decay * truth_weight
            if anchor_effective > 0:
                for p, anchor in zip(model.parameters(), app.state.anchor_params):
                    p.data.lerp_(anchor.to(p.device), anchor_effective)

            app.state.train_step_count += 1
            loss_val = loss.item()

            logger.info(
                "[TRAIN] step=%d, device=%s, DoT=%.3f, tw=%.2f, "
                "lr_scale=%.6f, warmup=%.3f, grad_norm=%.4f, loss=%.4f",
                app.state.train_step_count, train_device, dot, truth_weight,
                lr_scale, warmup, grad_norm.item() if hasattr(grad_norm, 'item') else grad_norm,
                loss_val,
            )

            # Move model back to inference device if we relocated it
            if model_device != train_device:
                model.to(model_device)

            key = "gain" if dot < 0 else "loss"
            return {"status": "ok", key: loss_val,
                    "step": app.state.train_step_count,
                    "grad_norm": grad_norm.item() if hasattr(grad_norm, 'item') else float(grad_norm)}

        except Exception as e:
            logger.error("[TRAIN] Error: %s", e)
            # Ensure model returns to inference device on error
            try:
                if model_device != train_device:
                    model.to(model_device)
            except Exception:
                pass
            return {"status": "error", "loss": None, "message": str(e)}
        finally:
            await worker_pool.release_worker(worker)


# ---------------------------------------------------------------------------
# Entry point — launch NanoChat with the /train route mounted
# ---------------------------------------------------------------------------
def start_server() -> None:
    """Launch NanoChat with WikiOracle extensions (online training route).

    This replaces ``python -m scripts.chat_web`` by mounting the /train
    route onto NanoChat's FastAPI app before starting uvicorn.

    All command-line arguments are the same as ``scripts.chat_web``.
    """
    from scripts.chat_web import app, args  # NanoChat's PYTHONPATH

    mount_train_route(app)

    import uvicorn

    print("Starting NanoChat Web Server (with WikiOracle /train extension)")
    print(f"Temperature: {args.temperature}, Top-k: {args.top_k}, Max tokens: {args.max_tokens}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    start_server()
