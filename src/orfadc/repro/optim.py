"""Small, dependency-free optimisers (PSO, SA, GA, GP-BO) on box bounds.

The paper uses scikit-opt; these re-implementations keep the same algorithm
families while staying deterministic under a seed and budget-aware.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

Objective = Callable[[np.ndarray], float]


@dataclass
class OptResult:
    x: np.ndarray
    f: float
    n_evals: int
    history: list[float] = field(default_factory=list)


def _scale(u: np.ndarray, lb: np.ndarray, ub: np.ndarray) -> np.ndarray:
    return lb + u * (ub - lb)


def pso(func: Objective, lb, ub, *, n_particles: int = 10, iters: int = 12, seed: int = 0,
        w: float = 0.6, c1: float = 1.5, c2: float = 1.5, stop_at: float | None = None,
        x0: np.ndarray | None = None) -> OptResult:
    lb, ub = np.asarray(lb, float), np.asarray(ub, float)
    rng = np.random.default_rng(seed)
    d = lb.size
    u = rng.random((n_particles, d))
    if x0 is not None:
        u[0] = np.clip((np.asarray(x0) - lb) / (ub - lb), 0, 1)
    v = 0.1 * rng.standard_normal((n_particles, d))
    f = np.array([func(_scale(p, lb, ub)) for p in u])
    n = n_particles
    pbest, pf = u.copy(), f.copy()
    g = int(np.argmin(pf))
    hist = [float(pf[g])]
    for _ in range(iters - 1):
        if stop_at is not None and pf[g] <= stop_at:
            break
        r1, r2 = rng.random((n_particles, d)), rng.random((n_particles, d))
        v = w * v + c1 * r1 * (pbest - u) + c2 * r2 * (pbest[g] - u)
        u = np.clip(u + v, 0.0, 1.0)
        f = np.array([func(_scale(p, lb, ub)) for p in u])
        n += n_particles
        better = f < pf
        pbest[better], pf[better] = u[better], f[better]
        g = int(np.argmin(pf))
        hist.append(float(pf[g]))
    return OptResult(_scale(pbest[g], lb, ub), float(pf[g]), n, hist)


def simulated_annealing(func: Objective, lb, ub, *, iters: int = 600, seed: int = 0, t0: float = 1.0,
                        t_end: float = 1e-3, step: float = 0.15, x0: np.ndarray | None = None,
                        stop_at: float | None = None) -> OptResult:
    lb, ub = np.asarray(lb, float), np.asarray(ub, float)
    rng = np.random.default_rng(seed)
    u = rng.random(lb.size) if x0 is None else np.clip((np.asarray(x0) - lb) / (ub - lb), 0, 1)
    fu = func(_scale(u, lb, ub))
    best, fbest = u.copy(), fu
    hist = [fbest]
    scale = None
    n = 1
    for i in range(iters):
        t = t0 * (t_end / t0) ** (i / max(iters - 1, 1))
        cand = np.clip(u + step * (0.3 + t) * rng.standard_normal(lb.size), 0, 1)
        fc = func(_scale(cand, lb, ub))
        n += 1
        if scale is None and fc != fu:
            scale = max(abs(fc - fu), 1e-6)
        de = (fc - fu) / (scale or 1.0)
        if de <= 0 or rng.random() < math.exp(-de / max(t, 1e-9)):
            u, fu = cand, fc
            if fu < fbest:
                best, fbest = u.copy(), fu
        hist.append(fbest)
        if stop_at is not None and fbest <= stop_at:
            break
    return OptResult(_scale(best, lb, ub), float(fbest), n, hist)


def genetic(func: Objective, lb, ub, *, pop: int = 20, gens: int = 20, seed: int = 0,
            pm: float = 0.15, stop_at: float | None = None, budget: int | None = None) -> OptResult:
    lb, ub = np.asarray(lb, float), np.asarray(ub, float)
    rng = np.random.default_rng(seed)
    d = lb.size
    p = rng.random((pop, d))
    f = np.array([func(_scale(x, lb, ub)) for x in p])
    n = pop
    hist = [float(f.min())]
    for _ in range(gens - 1):
        if stop_at is not None and f.min() <= stop_at:
            break
        if budget is not None and n + pop > budget:
            break
        children = []
        elite = p[np.argsort(f)[:2]]
        children.extend(elite)
        while len(children) < pop:
            i, j = rng.integers(0, pop, 2), rng.integers(0, pop, 2)
            a = p[i[np.argmin(f[i])]]
            b = p[j[np.argmin(f[j])]]
            alpha = rng.random(d)
            c = alpha * a + (1 - alpha) * b
            mask = rng.random(d) < pm
            c[mask] = np.clip(c[mask] + 0.2 * rng.standard_normal(mask.sum()), 0, 1)
            children.append(c)
        p = np.array(children)
        f = np.array([func(_scale(x, lb, ub)) for x in p])
        n += pop
        hist.append(float(min(hist[-1], f.min())))
    g = int(np.argmin(f))
    return OptResult(_scale(p[g], lb, ub), float(f[g]), n, hist)


def _erf(x: np.ndarray) -> np.ndarray:
    """Vectorised erf (Abramowitz-Stegun 7.1.26, |err| < 1.5e-7)."""
    sign = np.sign(x)
    x = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return sign * y


def bayes_opt(func: Objective, lb, ub, *, n_init: int = 10, iters: int = 40, seed: int = 0,
              n_cand: int = 2000, stop_at: float | None = None) -> OptResult:
    """GP-EI Bayesian optimisation (RBF kernel, fixed hyper-parameters on a
    log-transformed objective).  Adequate for the <=200-evaluation budgets here."""
    lb, ub = np.asarray(lb, float), np.asarray(ub, float)
    rng = np.random.default_rng(seed)
    d = lb.size
    xs = rng.random((n_init, d))
    ys = np.array([func(_scale(x, lb, ub)) for x in xs])
    hist = [float(ys.min())]
    ell = 0.25 * math.sqrt(d)

    def sqdist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.maximum((a * a).sum(1)[:, None] + (b * b).sum(1)[None, :] - 2.0 * a @ b.T, 0.0)

    for _ in range(iters):
        if stop_at is not None and ys.min() <= stop_at:
            break
        yt = np.log1p(np.maximum(ys, 0))
        mu0, sd0 = yt.mean(), yt.std() + 1e-9
        yn = (yt - mu0) / sd0
        kmat = np.exp(-0.5 * sqdist(xs, xs) / ell**2) + 1e-4 * np.eye(len(xs))
        lchol = np.linalg.cholesky(kmat)
        alpha = np.linalg.solve(lchol.T, np.linalg.solve(lchol, yn))
        cand = rng.random((n_cand, d))
        best = xs[np.argmin(ys)]
        cand[: n_cand // 4] = np.clip(best + 0.08 * rng.standard_normal((n_cand // 4, d)), 0, 1)
        kc = np.exp(-0.5 * sqdist(cand, xs) / ell**2)
        mu = kc @ alpha
        vv = np.linalg.solve(lchol, kc.T)
        var = np.maximum(1.0 - (vv**2).sum(0), 1e-12)
        sd = np.sqrt(var)
        fbest = yn.min()
        z = (fbest - mu) / sd
        cdf = 0.5 * (1 + _erf(z / math.sqrt(2)))
        pdf = np.exp(-0.5 * z**2) / math.sqrt(2 * math.pi)
        ei = (fbest - mu) * cdf + sd * pdf
        x = cand[int(np.argmax(ei))]
        y = func(_scale(x, lb, ub))
        xs = np.vstack([xs, x])
        ys = np.append(ys, y)
        hist.append(float(ys.min()))
    g = int(np.argmin(ys))
    return OptResult(_scale(xs[g], lb, ub), float(ys[g]), len(ys), hist)
