import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { getCampaigns } from "../lib/api"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer
} from "recharts"

interface Campaign {
  id: string
  status: string
  brief: string
  metrics: { open_rate: number; click_rate: number; total_sent: number }
  created_at: string
  iteration: number
}

const STATUS: Record<string, { label: string; cls: string }> = {
  planning:          { label: "Planning",       cls: "badge-planning" },
  awaiting_approval: { label: "Needs Approval", cls: "badge-awaiting" },
  running:           { label: "Running",         cls: "badge-running" },
  monitoring:        { label: "Monitoring",      cls: "badge-monitoring" },
  optimizing:        { label: "Optimizing",      cls: "badge-optimizing" },
  done:              { label: "Complete",        cls: "badge-done" },
  error:             { label: "Error",           cls: "badge-error" },
}

const ChartTip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <p style={{ color: "var(--t3)", marginBottom: 6 }}>{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} style={{ color: p.color, margin: "2px 0" }}>
          {p.name}: <strong>{p.value}%</strong>
        </p>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    getCampaigns().then(d => { setCampaigns(d as Campaign[]); setLoading(false) })
    const t = setInterval(() => getCampaigns().then(d => setCampaigns(d as Campaign[])), 12000)
    return () => clearInterval(t)
  }, [])

  const chartData = campaigns.map((c, i) => ({
    name: `C${i + 1}`,
    "Open Rate": Math.round(c.metrics.open_rate * 100),
    "Click Rate": Math.round(c.metrics.click_rate * 100),
  }))

  const totalSent = campaigns.reduce((s, c) => s + (c.metrics.total_sent || 0), 0)
  const avgClick = campaigns.length
    ? (campaigns.reduce((s, c) => s + c.metrics.click_rate, 0) / campaigns.length * 100).toFixed(1) : "—"
  const avgOpen = campaigns.length
    ? (campaigns.reduce((s, c) => s + c.metrics.open_rate, 0) / campaigns.length * 100).toFixed(1) : "—"
  const pending = campaigns.filter(c => c.status === "awaiting_approval").length
  const best = campaigns.reduce((b, c) => c.metrics.click_rate > (b?.metrics.click_rate || 0) ? c : b, null as Campaign | null)

  return (
    <div className="page">

      {/* ── TOP NAV ── */}
      <div className="anim-up" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "2.5rem" }}>
        <div>
          <div className="label" style={{ marginBottom: 8, color: "var(--t3)" }}>SuperBFSI · XDeposit Launch</div>
          <h1 className="font-display" style={{ fontSize: "2.1rem", fontWeight: 800, letterSpacing: "-0.025em", lineHeight: 1, color: "var(--t1)" }}>
            Campaign<span style={{ color: "var(--gold)" }}>X</span>
          </h1>
          <p style={{ color: "var(--t3)", fontSize: "0.83rem", marginTop: 6 }}>
            AI multi-agent marketing orchestration
          </p>
        </div>
        <button className="btn btn-gold" onClick={() => navigate("/new")}>
          ＋ New Campaign
        </button>
      </div>

      {/* ── STAT ROW ── */}
      <div className="anim-up delay-1" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: "0.85rem", marginBottom: "1.75rem" }}>
        {[
          { label: "Campaigns", value: campaigns.length, unit: "", color: "var(--purple)", bar: "linear-gradient(90deg,var(--purple),transparent)" },
          { label: "Avg Click Rate", value: avgClick, unit: "%", color: "var(--gold)", bar: "linear-gradient(90deg,var(--gold),transparent)" },
          { label: "Avg Open Rate", value: avgOpen, unit: "%", color: "var(--teal)", bar: "linear-gradient(90deg,var(--teal),transparent)" },
          { label: "Emails Sent", value: totalSent.toLocaleString(), unit: "", color: "var(--green)", bar: "linear-gradient(90deg,var(--green),transparent)" },
        ].map(s => (
          <div key={s.label} className="stat">
            <div className="label" style={{ marginBottom: 10 }}>{s.label}</div>
            <div className="font-display" style={{ fontSize: "1.75rem", fontWeight: 800, color: s.color, lineHeight: 1 }}>
              {s.value}{s.unit}
            </div>
            <div className="stat-bar" style={{ background: s.bar, opacity: 0.4 }} />
          </div>
        ))}
      </div>

      {/* ── PENDING ALERT ── */}
      {pending > 0 && (
        <div className="anim-up delay-2" style={{
          background: "rgba(245,200,66,0.04)",
          border: "1px solid rgba(245,200,66,0.2)",
          borderRadius: 12,
          padding: "0.9rem 1.25rem",
          marginBottom: "1.5rem",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <span style={{ fontSize: "1.1rem" }}>⚡</span>
            <div>
              <div className="font-display" style={{ fontWeight: 700, color: "var(--gold)", fontSize: "0.875rem" }}>
                {pending} campaign{pending > 1 ? "s" : ""} awaiting approval
              </div>
              <div style={{ color: "var(--t3)", fontSize: "0.78rem", marginTop: 2 }}>
                Human review required before sending emails
              </div>
            </div>
          </div>
          <button className="btn btn-gold btn-sm"
            onClick={() => { const c = campaigns.find(c => c.status === "awaiting_approval"); if (c) navigate(`/approve/${c.id}`) }}>
            Review Now →
          </button>
        </div>
      )}

      {/* ── MAIN GRID ── */}
      <div style={{ display: "grid", gridTemplateColumns: campaigns.length > 0 ? "1fr 340px" : "1fr", gap: "1.25rem" }}>

        {/* Campaign List */}
        <div className="anim-up delay-2">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.85rem" }}>
            <span className="label">All Campaigns</span>
            <span className="font-mono" style={{ fontSize: "0.65rem", color: "var(--t3)" }}>{campaigns.length} total</span>
          </div>

          {loading ? (
            <div className="card" style={{ padding: "3.5rem", textAlign: "center" }}>
              <div className="font-mono" style={{ color: "var(--t3)", fontSize: "0.78rem" }}>
                Fetching campaigns<span className="cursor" />
              </div>
            </div>
          ) : campaigns.length === 0 ? (
            <div className="card" style={{ padding: "4rem 2rem", textAlign: "center" }}>
              <div style={{ fontSize: "2.5rem", marginBottom: "1rem" }}>🚀</div>
              <div className="font-display" style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: 8 }}>No campaigns yet</div>
              <p style={{ color: "var(--t3)", fontSize: "0.875rem", marginBottom: "1.5rem" }}>
                Launch your first AI-powered XDeposit campaign
              </p>
              <button className="btn btn-gold" onClick={() => navigate("/new")}>Launch First Campaign</button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
              {[...campaigns].reverse().map((c, i) => {
                const cfg = STATUS[c.status] || STATUS.done
                const openPct = Math.round(c.metrics.open_rate * 100)
                const clickPct = Math.round(c.metrics.click_rate * 100)
                return (
                  <div key={c.id} className={`card anim-up delay-${Math.min(i + 2, 5)}`}
                    style={{ padding: "1.1rem 1.25rem", cursor: "pointer" }}
                    onClick={() => navigate(`/reports/${c.id}`)}>

                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.5rem", flexWrap: "wrap" }}>
                          <span className={`badge ${cfg.cls}`}>{cfg.label}</span>
                          <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--t3)" }}>#{c.id.slice(0, 8)}</span>
                          {(c.iteration || 1) > 1 && (
                            <span className="font-mono" style={{ fontSize: "0.6rem", background: "rgba(45,212,191,0.1)", color: "var(--teal)", padding: "2px 6px", borderRadius: 4, border: "1px solid rgba(45,212,191,0.2)" }}>
                              iter {c.iteration}
                            </span>
                          )}
                        </div>
                        <p style={{ color: "var(--t2)", fontSize: "0.83rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {c.brief.slice(0, 75)}…
                        </p>

                        {/* Progress bars */}
                        <div style={{ display: "flex", gap: "1.5rem", marginTop: "0.75rem" }}>
                          {[
                            { label: "Open", pct: openPct, color: "var(--teal)" },
                            { label: "Click", pct: clickPct, color: "var(--gold)" },
                          ].map(m => (
                            <div key={m.label} style={{ flex: 1 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                <span className="label">{m.label}</span>
                                <span className="font-mono" style={{ fontSize: "0.65rem", color: m.color }}>{m.pct}%</span>
                              </div>
                              <div className="prog-track">
                                <div className="prog-fill" style={{ width: `${m.pct}%`, background: m.color }} />
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Actions */}
                      <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", flexShrink: 0 }}
                           onClick={e => e.stopPropagation()}>
                        {c.status === "awaiting_approval" && (
                          <button className="btn btn-gold btn-sm" onClick={() => navigate(`/approve/${c.id}`)}>
                            Review
                          </button>
                        )}
                        <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/reports/${c.id}`)}>
                          Report
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Sidebar: chart + best performer */}
        {campaigns.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }} className="anim-up delay-3">

            <div>
              <div className="label" style={{ marginBottom: "0.85rem" }}>Performance</div>
              <div className="card" style={{ padding: "1.25rem" }}>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={chartData} barGap={3}>
                    <XAxis dataKey="name" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
                    <YAxis unit="%" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
                    <Bar dataKey="Open Rate" fill="var(--teal)" radius={[3,3,0,0]} maxBarSize={22} />
                    <Bar dataKey="Click Rate" fill="var(--gold)" radius={[3,3,0,0]} maxBarSize={22} />
                  </BarChart>
                </ResponsiveContainer>
                <div style={{ display: "flex", justifyContent: "center", gap: "1.25rem", marginTop: "0.5rem" }}>
                  {[{ color: "var(--teal)", label: "Open" }, { color: "var(--gold)", label: "Click" }].map(l => (
                    <div key={l.label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                      <div style={{ width: 8, height: 8, borderRadius: 2, background: l.color }} />
                      <span className="label">{l.label} Rate</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Best performer */}
            {best && (
              <div>
                <div className="label" style={{ marginBottom: "0.85rem" }}>Best Performer</div>
                <div className="card card-accent" style={{ padding: "1.1rem 1.25rem", cursor: "pointer" }}
                     onClick={() => navigate(`/reports/${best.id}`)}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                    <span className="font-mono" style={{ fontSize: "0.6rem", color: "var(--t3)" }}>#{best.id.slice(0,8)}</span>
                    <span className="font-mono" style={{ fontSize: "0.7rem", color: "var(--gold)", fontWeight: 600 }}>
                      {Math.round(best.metrics.click_rate * 100)}% CTR
                    </span>
                  </div>
                  <p style={{ color: "var(--t2)", fontSize: "0.78rem" }}>
                    {best.brief.slice(0, 60)}…
                  </p>
                </div>
              </div>
            )}

          </div>
        )}
      </div>
    </div>
  )
}
