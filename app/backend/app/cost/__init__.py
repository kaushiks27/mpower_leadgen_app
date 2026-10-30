"""Cost-transparency feature package — read-only monthly cost estimator.

Re-exports the router for `main.py` registration (OP #11). Pure-Decimal cost
math lives in `calculator.py`; the router is a thin admin-gated GET that returns
the estimate. No DB writes — this surface only reads constants + two query knobs
(USD->INR rate, monthly email volume), so it never touches pipeline state.
"""

from app.cost.router import router

__all__ = ["router"]
