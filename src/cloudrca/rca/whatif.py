"""What-if simulator (plan §4.6): reuse the SCM, apply an intervention, report predicted deltas.
Always label output as a model estimate."""
from __future__ import annotations
from .m3_cost import LinearSCM


def what_if(scm: LinearSCM, post, intervention: dict, targets: list[str]) -> dict:
    base = scm.simulate(post)
    new = scm.simulate(post, intervention)
    return {t: dict(before=float(base[t].mean()), after=float(new[t].mean()),
                    delta=float(new[t].mean() - base[t].mean())) for t in targets} | {"_note": "model estimate"}
