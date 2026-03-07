import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { getCampaigns } from "../lib/api"

interface Campaign {
  id: string
  status: string
  brief: string
  metrics: { open_rate: number; click_rate: number; total_sent: number }
  created_at: string
  iteration: number
  strategy?: { segments?: any[]; ab_variants?: any[] }
  emails?: any[]
}

const STATUS: Record<string, { label: string; cls: string; icon: string }> = {
  planning:          { label: "Planning",       cls: "badge-planning",   icon: "◌" },
  awaiting_approval: { label: "Needs Approval", cls: "badge-awaiting",   icon: "⚡" },
  running:           { label: "Running",         cls: "badge-running",    icon: "▶" },
  monitoring:        { label: "Monitoring",      cls: "badge-monitoring", icon: "◐" },
  optimizing:        { label: "Optimizing",      cls: "badge-optimizing", icon: "⟳" },
  done:              { label: "Complete",        cls: "badge-done",       icon: "✓" },
  error:             { label: "Error",           cls: "badge-error",      icon: "✕" },
}

function fmtDate(iso: string) {
  if (!iso) return "—"
  const d = new Date(iso)
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) + " · " +
         d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
}

export default function History() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<string>("all")
  const [expanded, setExpanded] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    getCampaigns().then(d => { setCampaigns((d as Campaign[]).reverse()); setLoading(false) })
  }, [])

  const statuses = ["all", "done", "awaiting_approval", "optimizing", "error"]
  const filtered = filter === "all" ? campaigns : campaigns.filter(c => c.status === filter)

  return (
    <div className="page">
      {/* Header */}
      <div className="anim-up" style={{ marginBottom: "2rem" }}>
        <div className="label" style={{ marginBottom: 6 }}>Audit Trail</div>
        <h1 className="font-display" style={{ fontSize: "1.9rem", fontWeight: 800, letterSpacing: "-0.025em" }}>
          Campaign History
        </h1>
        <p style={{ color: "var(--t3)", fontSize: "0.83rem", marginTop: 5 }}>
          Full log of all campaign runs, iterations, and decisions
        </p>
      </div>

      {/* Filters */}
      <div className="anim-up delay-1" style={{ marginBottom: "1.5rem" }}>
        <div className="tab-bar" style={{ display: "inline-flex" }}>
          {statuses.map(s => (
            <button key={s} className={`tab ${filter === s ? "active" : ""}`}
                    onClick={() => setFilter(s)}>
              {s === "all" ? "All" : STATUS[s]?.label || s}
            </button>
          ))}
        </div>
      </div>

      {/* Summary strip */}
      <div className="anim-up delay-1" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: "0.85rem", marginBottom: "1.75rem" }}>
        {[
          { label: "Total Runs", value: campaigns.length, color: "var(--purple)" },
          { label: "Completed", value: campaigns.filter(c => c.status === "done").length, color: "var(--green)" },
          { label: "In Progress", value: campaigns.filter(c => !["done","error"].includes(c.status)).length, color: "var(--gold)" },
          { label: "Errors", value: campaigns.filter(c => c.status === "error").length, color: "var(--red)" },
        ].map(s => (
          <div key={s.label} className="stat">
            <div className="label" style={{ marginBottom: 8 }}>{s.label}</div>
            <div className="font-display" style={{ fontSize: "1.75rem", fontWeight: 800, color: s.color }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Timeline */}
      {loading ? (
        <div className="card" style={{ padding: "3rem", textAlign: "center" }}>
          <span className="font-mono" style={{ color: "var(--t3)", fontSize: "0.8rem" }}>
            Loading history<span className="cursor" />
          </span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ padding: "3.5rem", textAlign: "center" }}>
          <div style={{ fontSize: "2rem", marginBottom: "0.75rem" }}>📭</div>
          <div className="font-display" style={{ fontWeight: 700, marginBottom: 6 }}>No campaigns found</div>
          <p style={{ color: "var(--t3)", fontSize: "0.83rem" }}>
            {filter !== "all" ? "Try a different filter" : "Launch your first campaign to see history"}
          </p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0", position: "relative" }}>
          {/* Timeline line */}
          <div style={{
            position: "absolute", left: 18, top: 24, bottom: 24,
            width: 1, background: "linear-gradient(to bottom, var(--gold), var(--border))",
            opacity: 0.3, zIndex: 0,
          }} />

          {filtered.map((c, i) => {
            const cfg = STATUS[c.status] || STATUS.done
            const openPct = Math.round(c.metrics.open_rate * 100)
            const clickPct = Math.round(c.metrics.click_rate * 100)
            const isExpanded = expanded === c.id

            return (
              <div key={c.id} className="anim-up" style={{ animationDelay: `${i * 0.04}s`, display: "flex", gap: "1.25rem", marginBottom: "0.85rem", position: "relative", zIndex: 1 }}>
                {/* Timeline dot */}
                <div style={{
                  width: 36, height: 36, borderRadius: "50%",
                  background: c.status === "done" ? "rgba(74,222,128,0.12)" : "var(--card)",
                  border: `1px solid ${c.status === "done" ? "rgba(74,222,128,0.25)" : "var(--border)"}`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0, fontSize: "0.9rem",
                  fontFamily: "'JetBrains Mono', monospace",
                  color: c.status === "done" ? "var(--green)" : "var(--t3)",
                  marginTop: 4,
                }}>
                  {cfg.icon}
                </div>

                {/* Card */}
                <div className="card" style={{ flex: 1, overflow: "hidden" }}>
                  <div
                    style={{ padding: "1rem 1.25rem", cursor: "pointer" }}
                    onClick={() => setExpanded(isExpanded ? null : c.id)}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.75rem" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.4rem", flexWrap: "wrap" }}>
                          <span className={`badge ${cfg.cls}`}>{cfg.label}</span>
                          <span className="font-mono" style={{ fontSize: "0.58rem", color: "var(--t4)" }}>
                            #{c.id.slice(0, 8)}
                          </span>
                          {(c.iteration || 1) > 1 && (
                            <span className="font-mono" style={{ fontSize: "0.58rem", color: "var(--teal)", background: "rgba(45,212,191,0.08)", padding: "1px 5px", borderRadius: 3, border: "1px solid rgba(45,212,191,0.15)" }}>
                              {c.iteration} iterations
                            </span>
                          )}
                        </div>
                        <p style={{ color: "var(--t2)", fontSize: "0.83rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {c.brief.slice(0, 90)}…
                        </p>
                        <div className="font-mono" style={{ fontSize: "0.6rem", color: "var(--t4)", marginTop: 5 }}>
                          {fmtDate(c.created_at)}
                        </div>
                      </div>

                      {/* Metrics */}
                      <div style={{ display: "flex", gap: "1.25rem", flexShrink: 0, alignItems: "center" }}>
                        <div style={{ textAlign: "right" }}>
                          <div className="label">Open</div>
                          <div className="font-display" style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--teal)" }}>{openPct}%</div>
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <div className="label">Click</div>
                          <div className="font-display" style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--gold)" }}>{clickPct}%</div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <button className="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); navigate(`/reports/${c.id}`) }}>
                            Report
                          </button>
                          {c.status === "awaiting_approval" && (
                            <button className="btn btn-gold btn-sm" onClick={e => { e.stopPropagation(); navigate(`/approve/${c.id}`) }}>
                              Review
                            </button>
                          )}
                        </div>
                        <span style={{ color: "var(--t4)", fontSize: "0.7rem", transition: "transform 0.2s", transform: isExpanded ? "rotate(180deg)" : "none" }}>▾</span>
                      </div>
                    </div>
                  </div>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div style={{ borderTop: "1px solid var(--border)", padding: "1rem 1.25rem", background: "rgba(0,0,0,0.15)" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem" }}>
                        <div>
                          <div className="label" style={{ marginBottom: 6 }}>Campaign Brief</div>
                          <p style={{ color: "var(--t2)", fontSize: "0.78rem", lineHeight: 1.65 }}>
                            {c.brief.slice(0, 200)}{c.brief.length > 200 ? "…" : ""}
                          </p>
                        </div>
                        <div>
                          <div className="label" style={{ marginBottom: 6 }}>Strategy</div>
                          <div style={{ color: "var(--t2)", fontSize: "0.78rem", lineHeight: 1.8 }}>
                            <div>Segments: <span style={{ color: "var(--t1)" }}>{c.strategy?.segments?.length || 0}</span></div>
                            <div>A/B Variants: <span style={{ color: "var(--t1)" }}>{c.emails?.length || 0}</span></div>
                            <div>Total Sent: <span style={{ color: "var(--t1)" }}>{c.metrics.total_sent?.toLocaleString() || 0}</span></div>
                            <div>Iterations: <span style={{ color: "var(--t1)" }}>{c.iteration || 1}</span></div>
                          </div>
                        </div>
                        <div>
                          <div className="label" style={{ marginBottom: 6 }}>Performance</div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                            {[{ label: "Open Rate", pct: openPct, color: "var(--teal)" }, { label: "Click Rate", pct: clickPct, color: "var(--gold)" }].map(m => (
                              <div key={m.label}>
                                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                  <span className="label">{m.label}</span>
                                  <span className="font-mono" style={{ fontSize: "0.62rem", color: m.color }}>{m.pct}%</span>
                                </div>
                                <div className="prog-track">
                                  <div className="prog-fill" style={{ width: `${m.pct}%`, background: m.color }} />
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
