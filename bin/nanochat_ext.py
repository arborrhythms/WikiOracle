"""WikiOracle extensions mounted onto NanoChat's FastAPI app.

This module defines routes that are added to the NanoChat ``app`` object
**from WikiOracle's codebase** so that NanoChat's own source files remain
unmodified.  The only route so far is ``POST /train`` for online learning.

Usage (from ``bin/start_nanochat.py``):

    from nanochat.scripts.chat_web import app
    from nanochat_ext import mount_train_route
    mount_train_route(app)
    uvicorn.run(app, ...)
"""

from __future__ import annotations

import logging
from typing import List

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


# ---------------------------------------------------------------------------
# Mount helper
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


def mount_train_route(app: FastAPI) -> None:
    """Register ``POST /train`` on *app* (NanoChat's FastAPI instance)."""

    @app.post("/train")
    async def train(request: TrainRequest):
        """Online training endpoint: one forward + backward + optimizer step.

        Input:  ``{"messages": [...], "degree_of_truth": -1.0–1.0}``

        DoT semantics (range **-1 .. +1**)::

            +1  = the exchange is fully true   → train at full learning rate
             0  = no information / neutral      → skip (nothing to learn)
            -1  = the exchange is fully false   → train at full lr (learning
                  what is *not* true is as valuable as learning what *is* true)

        Learning rate is scaled by ``|degree_of_truth|``::

            group["lr"] = group["initial_lr"] × |degree_of_truth|

        A DoT near 0 means the truth table offers no signal for this
        exchange.  In a consensus truth model this is simply a skip.  In
        a future pluralistic model — where the same claim can be true in
        context c1 and false in context c2 — a DoT of 0 would indicate
        that user feedback is needed to disambiguate before training
        should proceed.

        Returns ``{"status": "ok", "loss": float}`` or a no-op dict.
        """
        worker_pool = getattr(app.state, "worker_pool", None)
        if worker_pool is None or len(worker_pool.workers) == 0:
            return {"status": "ok", "loss": None, "message": "no model loaded"}

        dot = max(-1.0, min(1.0, request.degree_of_truth))
        if abs(dot) < 1e-6:
            # DoT ≈ 0: no agreement or disagreement signal — skip.
            # NOTE: in a pluralistic truth model, this might instead
            # trigger a request for user feedback to resolve which
            # context applies before committing a training step.
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

            # Resolve training device (config-driven; defaults to cpu)
            train_device = _resolve_device(request.device)

            # Move model to training device if it differs from inference device
            model_device = next(model.parameters()).device
            if model_device != train_device:
                logger.info("[TRAIN] Moving model %s → %s for training step",
                            model_device, train_device)
                model.to(train_device)

            # Build optimizer if not already present
            if not hasattr(app.state, "optimizer"):
                app.state.optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
                for group in app.state.optimizer.param_groups:
                    group["initial_lr"] = group["lr"]

            optimizer = app.state.optimizer

            # Scale learning rates by |degree_of_truth|.
            # Both +1 (true) and -1 (false) train at full strength —
            # the sign encodes direction (agree/disagree), not magnitude.
            # The model learns equally from confirmed truths and refuted
            # falsehoods; only DoT ≈ 0 (no signal) is skipped above.
            lr_scale = abs(dot)
            for group in optimizer.param_groups:
                group["lr"] = group.get("initial_lr", 1e-4) * lr_scale

            # Forward + backward + optimizer step
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
            optimizer.step()
            model.eval()

            loss_val = loss.item()
            logger.info(
                "[TRAIN] device=%s, DoT=%.3f, lr=%.6f, loss=%.4f",
                train_device, dot, optimizer.param_groups[0]["lr"], loss_val,
            )

            # Move model back to inference device if we relocated it
            if model_device != train_device:
                model.to(model_device)

            key = "gain" if dot < 0 else "loss"
            return {"status": "ok", key: loss_val}

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
