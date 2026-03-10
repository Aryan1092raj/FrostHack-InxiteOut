"""
Thompson Sampling for email variant selection.

Uses Beta distribution to model click-rate uncertainty per variant.
Each variant starts with Beta(α=1, β=1) — uninformed prior.
After observing clicks/total, α += clicks, β += (total - clicks).

Why this beats A/B testing:
  - A/B wastes 50% of budget on the loser until the test ends.
  - Thompson continuously shifts traffic toward the winner AS data comes in.
  - With a gamified API (instant results), convergence is near-immediate.
"""

import random
import math


class ThompsonSampler:
    def __init__(self):
        self.variants: dict[str, dict] = {}

    def add_variant(self, variant_id: str, prior_alpha: float = 1.0, prior_beta: float = 1.0):
        """Register a variant. Alpha/beta represent prior belief — default = uniform."""
        self.variants[variant_id] = {
            "alpha": prior_alpha,
            "beta": prior_beta,
            "total_sent": 0,
            "total_clicks": 0,
        }

    def update(self, variant_id: str, clicks: int, total: int):
        """Update posterior with observed results."""
        if variant_id not in self.variants:
            self.add_variant(variant_id)
        self.variants[variant_id]["alpha"] += clicks
        self.variants[variant_id]["beta"] += max(total - clicks, 0)
        self.variants[variant_id]["total_sent"] += total
        self.variants[variant_id]["total_clicks"] += clicks

    def sample_once(self, variant_id: str) -> float:
        """Draw one sample from this variant's Beta posterior."""
        v = self.variants[variant_id]
        return random.betavariate(v["alpha"], v["beta"])

    def get_winner(self, n_samples: int = 1000) -> str:
        """
        Run n_samples Thompson draws. Winner = variant that wins most often.
        More samples = more confident selection (at low cost — it's pure math).
        """
        win_counts: dict[str, int] = {vid: 0 for vid in self.variants}
        for _ in range(n_samples):
            scores = {vid: self.sample_once(vid) for vid in self.variants}
            winner = max(scores, key=scores.get)
            win_counts[winner] += 1
        return max(win_counts, key=win_counts.get)

    def expected_click_rate(self, variant_id: str) -> float:
        """Mode of Beta distribution = (α-1)/(α+β-2) for α,β > 1, else mean = α/(α+β)."""
        v = self.variants[variant_id]
        a, b = v["alpha"], v["beta"]
        if a > 1 and b > 1:
            return (a - 1) / (a + b - 2)
        return a / (a + b)

    def confidence_interval(self, variant_id: str, confidence: float = 0.95) -> tuple[float, float]:
        """
        Approximate 95% CI using normal approximation to Beta.
        Returns (lower, upper) click rate bounds.
        """
        v = self.variants[variant_id]
        a, b = v["alpha"], v["beta"]
        mean = a / (a + b)
        variance = (a * b) / ((a + b) ** 2 * (a + b + 1))
        std = math.sqrt(variance)
        z = 1.96  # 95% CI
        return (max(0, mean - z * std), min(1, mean + z * std))

    def get_rankings(self) -> list[dict]:
        """Return all variants ranked by expected click rate with full stats."""
        ranked = []
        for vid, v in self.variants.items():
            lo, hi = self.confidence_interval(vid)
            ranked.append({
                "variant_id": vid,
                "expected_click_rate": round(self.expected_click_rate(vid), 4),
                "observed_click_rate": round(v["total_clicks"] / max(v["total_sent"], 1), 4),
                "total_sent": v["total_sent"],
                "total_clicks": v["total_clicks"],
                "confidence_interval": (round(lo, 4), round(hi, 4)),
                "alpha": round(v["alpha"], 2),
                "beta": round(v["beta"], 2),
            })
        return sorted(ranked, key=lambda x: x["expected_click_rate"], reverse=True)

    def is_confident_winner(self, threshold: float = 0.80) -> bool:
        """
        Returns True if the leading variant wins more than `threshold` fraction
        of Thompson draws. threshold=0.80 means 80% confidence.
        """
        if len(self.variants) < 2:
            return True
        win_counts = {vid: 0 for vid in self.variants}
        n = 500
        for _ in range(n):
            scores = {vid: self.sample_once(vid) for vid in self.variants}
            win_counts[max(scores, key=scores.get)] += 1
        top_fraction = max(win_counts.values()) / n
        return top_fraction >= threshold

    def summary_str(self) -> str:
        lines = ["Thompson Sampling Rankings:"]
        for i, r in enumerate(self.get_rankings()):
            ci = r["confidence_interval"]
            lines.append(
                f"  #{i+1} {r['variant_id']}: expected {r['expected_click_rate']:.1%} "
                f"(observed {r['observed_click_rate']:.1%}, n={r['total_sent']}, "
                f"95% CI [{ci[0]:.1%}, {ci[1]:.1%}])"
            )
        return "\n".join(lines)
