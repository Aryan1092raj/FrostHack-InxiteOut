from typing import TypedDict, Optional, List, Any


class CampaignState(TypedDict):
    # ── Core ──────────────────────────────────────────────────────────────────
    campaign_id:              str
    brief:                    str
    customers:                List[dict]       # Full cohort (from profiler)
    segments:                 List[dict]       # Built by profiler (now occupation-aware)
    strategy:                 dict             # Built by strategist
    emails:                   List[dict]       # Built by content_gen
    external_campaign_ids:    List[str]        # Returned by send_campaign API
    metrics:                  dict             # Computed by monitor
    iteration:                int              # Current loop count
    max_iterations:           int              # Stop after this many
    rejection_reason:         Optional[str]    # Set if human rejects
    optimization_notes:       str              # Passed from optimizer → strategist
    status:                   str              # planning|probe_done|running|monitored|optimizing|done|error
    underperforming_customer_ids: List[str]    # Customers who did NOT click last run
    winning_variant_info:     dict             # Best variant's subject/tone/click_rate
    all_emailed_customer_ids: List[str]        # Cumulative IDs emailed across all iterations
    all_converted_customer_ids: List[str]      # EC=Y across ALL iterations — NEVER re-target these

    # ── Innovation #1: Thompson Sampling / Probe → Exploit ────────────────────
    probe_results:            List[dict]       # [{probe_id, subject, body, click_rate, open_rate, dna}]
    thompson_winner:          dict             # Winning probe: {subject, body, tone, dna, click_rate, ...}
    main_pool_customer_ids:   List[str]        # 90% of cohort reserved for main campaign post-probe

    # ── Innovation #2: Email DNA ───────────────────────────────────────────────
    email_dna_signal:         dict             # {feature: {value: avg_click_rate}} from probe correlation
    winning_dna:              dict             # {feature: best_value} — hard constraints for content_gen
    dna_content_rules:        str             # Natural language DNA rules injected into content_gen prompt

    # ── Innovation #3: Occupation-Axis Segmentation ───────────────────────────
    # (stored inside segments[i]["occupation_breakdown"] dict per segment)

    # ── Innovation #4: API Signal Map (reverse-engineered from probes) ─────────
    # (stored inside email_dna_signal — probes ARE the signal experiments)
    # Additional cross-campaign signal accumulated here:
    api_signal_history:       List[dict]       # [{iteration, dna, click_rate}] across ALL campaigns
