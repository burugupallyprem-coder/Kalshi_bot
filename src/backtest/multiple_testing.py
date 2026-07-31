"""Multiple-testing correction - the module that keeps an automated strategy search HONEST.

The core problem of any "search until it passes" engine: test N strategies and the best
one looks good BY CHANCE. This quantifies and corrects for exactly that.

- Probabilistic Sharpe Ratio (PSR): confidence the TRUE per-period Sharpe exceeds a
  benchmark, given sample length, skew, and kurtosis.
- Deflated Sharpe Ratio (DSR): PSR where the benchmark is the EXPECTED MAXIMUM Sharpe
  under the null across N trials - i.e. how good the best-of-N would look by pure luck.
  A candidate is only a real lead if its DSR clears a high bar (e.g. 0.95).

Refs: Bailey & Lopez de Prado, "The Deflated Sharpe Ratio" (2014).
No scipy dependency - the normal CDF/PPF are implemented inline.
"""

import math


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p):
    """Inverse normal CDF (Acklam's algorithm)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def probabilistic_sharpe_ratio(sr, n, skew=0.0, kurt=3.0, sr_benchmark=0.0):
    """P(true per-period Sharpe > sr_benchmark). sr = per-observation Sharpe; n = obs."""
    if n < 2:
        return 0.0
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr))
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / denom
    return norm_cdf(z)


def expected_max_sharpe(n_trials, var_trials):
    """Expected value of the MAX of n_trials Sharpes under the null (mean 0, given variance)."""
    if n_trials < 2 or var_trials <= 0:
        return 0.0
    g = 0.5772156649015329  # Euler-Mascheroni
    a = norm_ppf(1.0 - 1.0 / n_trials)
    b = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_trials) * ((1 - g) * a + g * b)


def deflated_sharpe_ratio(sr_best, n_obs, trial_sharpes, skew=0.0, kurt=3.0):
    """DSR = confidence the BEST strategy of N trials is real, not the luckiest draw.
    Returns (dsr, expected_max_under_null)."""
    m = len(trial_sharpes)
    if m > 1:
        mean = sum(trial_sharpes) / m
        var = sum((s - mean) ** 2 for s in trial_sharpes) / (m - 1)
    else:
        var = 0.0
    sr0 = expected_max_sharpe(m, var)
    return probabilistic_sharpe_ratio(sr_best, n_obs, skew, kurt, sr0), sr0


def per_trade_sharpe(r_multiples):
    """Per-trade Sharpe + moments from a list of trade R-multiples (bridges an R-based
    engine to the DSR framework). Returns (sharpe, n, skew, kurt)."""
    r = [float(x) for x in r_multiples]
    n = len(r)
    if n < 2:
        return 0.0, n, 0.0, 3.0
    mean = sum(r) / n
    var = sum((x - mean) ** 2 for x in r) / (n - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd < 1e-10:
        return 0.0, n, 0.0, 3.0
    skew = (sum((x - mean) ** 3 for x in r) / n) / sd ** 3
    kurt = (sum((x - mean) ** 4 for x in r) / n) / sd ** 4
    return mean / sd, n, skew, kurt
