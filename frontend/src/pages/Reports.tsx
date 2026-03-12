import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { getCampaign, getCampaignReports } from "../lib/api"
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid
} from "recharts"

const ChartTip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <p style={{ color: "var(--t3)", marginBottom: 6 }}>{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} style={{ color: p.color || p.stroke, margin: "2px 0" }}>
          {p.name}: <strong>{p.value}%</strong>
        </p>
      ))}
    </div>
  )
}

export default function Reports() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [campaign, setCampaign] = useState<any>(null)
  const [reports, setReports] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<"overview" | "segments" | "ab" | "analysis">("overview")

  useEffect(() => {
    const fetch = () =>
      Promise.all([getCampaign(id!), getCampaignReports(id!)]).then(([c, r]) => {
        setCampaign(c); setReports(r); setLoading(false)
      })
    fetch()
    const t = setInterval(fetch, 8000)
    return () => clearInterval(t)
  }, [id])

  if (loading || !campaign) return (
    <div className="page" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "60vh" }}>
      <div className="font-mono" style={{ color: "var(--t3)", fontSize: "0.8rem" }}>
        Loading report<span className="cursor" />
      </div>
    </div>
  )

  const latestReport = reports[reports.length - 1]
  const rawData: any[] = latestReport?.raw_report?.data || []
  const segments: any[] = campaign.strategy?.segments || []
  const emails: any[] = campaign.emails || []

  // ── FIX: Build historyData grouped by iteration_number ────────────────────
  // OLD: hardcoded `i += 2` assumed exactly 2 variants per cycle — breaks with
  //      1 variant, 3 variants, or probe + main sends.
  // NEW: group by iteration_number field, fall back to hour-bucket grouping.
  const historyData: { cycle: string; "Open Rate": number; "Click Rate": number }[] = []

  if (reports.length > 0) {
    const iterationMap = new Map<number, any[]>()
    let hasIterationField = false

    reports.forEach((r: any) => {
      const iter = r.iteration_number ?? r.iteration ?? null
      if (iter !== null) {
        hasIterationField = true
        if (!iterationMap.has(iter)) iterationMap.set(iter, [])
        iterationMap.get(iter)!.push(r)
      }
    })

    if (hasIterationField && iterationMap.size > 0) {
      // Best path: grouped by actual iteration number
      Array.from(iterationMap.entries())
        .sort(([a], [b]) => a - b)
        .forEach(([, group], idx) => {
          const totalSent = group.reduce((s: number, r: any) => s + (r.total_sent || 0), 0)
          const weightedOpen = totalSent > 0
            ? Math.round(group.reduce((s: number, r: any) => s + (r.open_rate || 0) * (r.total_sent || 0), 0) / totalSent * 100)
            : 0
          const weightedClick = totalSent > 0
            ? Math.round(group.reduce((s: number, r: any) => s + (r.click_rate || 0) * (r.total_sent || 0), 0) / totalSent * 100)
            : 0
          historyData.push({ cycle: `Cycle ${idx + 1}`, "Open Rate": weightedOpen, "Click Rate": weightedClick })
        })
    } else {
      // Fallback: group by hour bucket (handles legacy data without iteration_number)
      const timeMap = new Map<string, any[]>()
      reports.forEach((r: any) => {
        const key = r.fetched_at ? r.fetched_at.slice(0, 13) : String(reports.indexOf(r))
        if (!timeMap.has(key)) timeMap.set(key, [])
        timeMap.get(key)!.push(r)
      })
      Array.from(timeMap.entries()).forEach(([, group], idx) => {
        const totalSent = group.reduce((s: number, r: any) => s + (r.total_sent || 0), 0)
        const weightedOpen = totalSent > 0
          ? Math.round(group.reduce((s: number, r: any) => s + (r.open_rate || 0) * (r.total_sent || 0), 0) / totalSent * 100)
          : 0
        const weightedClick = totalSent > 0
          ? Math.round(group.reduce((s: number, r: any) => s + (r.click_rate || 0) * (r.total_sent || 0), 0) / totalSent * 100)
          : 0
        historyData.push({ cycle: `Cycle ${idx + 1}`, "Open Rate": weightedOpen, "Click Rate": weightedClick })
      })
    }
  }

  // Segment performance
  const segData = segments.map((seg: any) => {
    const ids = new Set(seg.customer_ids || [])
    const rows = rawData.filter(r => ids.has(r.customer_id))
    const total = rows.length || 1
    return {
      segment: seg.name?.split(" ").slice(0, 2).join(" ") || "Seg",
      "Open Rate": Math.round(rows.filter(r => r.EO === "Y").length / total * 100),
      "Click Rate": Math.round(rows.filter(r => r.EC === "Y").length / total * 100),
    }
  }).filter(s => s["Open Rate"] > 0 || s["Click Rate"] > 0)

  // A/B data
  const abData = emails.map((email: any) => {
    const ids = new Set(email.customer_ids || [])
    const rows = rawData.filter(r => ids.has(r.customer_id))
    const total = rows.length || 1
    return {
      variant: (email.variant || "variant").replace("_", " ").toUpperCase(),
      "Open Rate": Math.round(rows.filter(r => r.EO === "Y").length / total * 100),
      "Click Rate": Math.round(rows.filter(r => r.EC === "Y").length / total * 100),
    }
  })

  const analysis = campaign.metrics?.analysis
    || latestReport?.raw_report?.computed_metrics?.analysis
    || null

  // ── FIX: Header stats now use same source as chart ────────────────────────
  // OLD: latestOpen/latestClick pulled from latestReport (single variant) while
  //      chart used weighted average across all variants → numbers diverged.
  // NEW: both read from historyData's latest cycle — always identical.
  const latestCycle  = historyData[historyData.length - 1]
  const latestOpen   = latestCycle?.["Open Rate"]  ?? Math.round((campaign.metrics?.open_rate  || 0) * 100)
  const latestClick  = latestCycle?.["Click Rate"] ?? Math.round((campaign.metrics?.click_rate || 0) * 100)
  const totalSent    = campaign.metrics?.total_sent || 0
  const numCycles    = historyData.length || campaign.iteration || Math.ceil(reports.length / 2)

  const TABS = [
    { key: "overview", label: "Overview" },
    { key: "segments", label: "Segments" },
    { key: "ab", label: "A/B Test" },
    { key: "analysis", label: "AI Insights" },
  ] as const

  return (
    <div className="page">

      {/* Header */}
      <div className="anim-up" style={{ marginBottom: "2rem" }}>
        <button className="back-link" style={{ marginBottom: "1.5rem" }} onClick={() => navigate("/")}>
          ← Dashboard
        </button>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
          <div>
            <div className="label" style={{ marginBottom: 6 }}>Performance Report</div>
            <h1 className="font-display" style={{ fontSize: "1.9rem", fontWeight: 800, letterSpacing: "-0.025em" }}>
              Campaign Analysis
            </h1>
            <p style={{ color: "var(--t3)", fontSize: "0.83rem", marginTop: 5 }}>
              #{id!.slice(0, 8)} · {numCycles} optimization cycle{numCycles !== 1 ? "s" : ""} completed
            </p>
          </div>
          <span className={`badge badge-${campaign.status.replace("awaiting_approval", "awaiting")}`} style={{ marginTop: 6 }}>
            {campaign.status?.replace(/_/g, " ")}
          </span>
        </div>
      </div>

      {/* Re-approval banner */}
      {campaign.status === "awaiting_approval" && (
        <div className="anim-up delay-1" style={{
          marginBottom: "1.25rem", padding: "1rem 1.25rem",
          background: "rgba(245,200,66,0.06)", border: "1px solid rgba(245,200,66,0.2)",
          borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem"
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <span style={{ fontSize: "1.2rem" }}>⚡</span>
            <div>
              <div className="font-display" style={{ fontWeight: 700, fontSize: "0.875rem" }}>
                Optimized Campaign Needs Approval
              </div>
              <p style={{ color: "var(--t3)", fontSize: "0.75rem", marginTop: 2 }}>
                AI agent has re-optimized based on performance. Review the updated strategy before re-launch.
              </p>
            </div>
          </div>
          <button className="btn btn-gold" onClick={() => navigate(`/approve/${id}`)}>
            Review & Approve
          </button>
        </div>
      )}

      {/* KPI Row */}
      <div className="anim-up delay-1" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: "0.85rem", marginBottom: "1.75rem" }}>
        {[
          { label: "Open Rate",   value: `${latestOpen}%`,              color: "var(--teal)",   prog: latestOpen,  bar: "var(--teal)"   },
          { label: "Click Rate",  value: `${latestClick}%`,             color: "var(--gold)",   prog: latestClick, bar: "var(--gold)"   },
          { label: "Emails Sent", value: totalSent.toLocaleString(),    color: "var(--purple)", prog: 0,           bar: "var(--purple)" },
          { label: "Iterations",  value: String(numCycles),             color: "var(--orange)", prog: 0,           bar: "var(--orange)" },
        ].map(s => (
          <div key={s.label} className="stat">
            <div className="label" style={{ marginBottom: 8 }}>{s.label}</div>
            <div className="font-display" style={{ fontSize: "1.75rem", fontWeight: 800, color: s.color, lineHeight: 1 }}>
              {s.value}
            </div>
            {s.prog > 0 && (
              <div className="prog-track" style={{ marginTop: 10 }}>
                <div className="prog-fill" style={{ width: `${Math.min(s.prog, 100)}%`, background: s.bar }} />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="anim-up delay-1" style={{ marginBottom: "1.25rem" }}>
        <div className="tab-bar" style={{ display: "inline-flex" }}>
          {TABS.map(t => (
            <button key={t.key} className={`tab ${tab === t.key ? "active" : ""}`}
                    onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab: Overview */}
      {tab === "overview" && (
        <div className="anim-in">
          <div className="card" style={{ padding: "1.5rem", marginBottom: "1rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.25rem" }}>
              <div>
                <div className="label" style={{ marginBottom: 4 }}>Optimization Loop Progress</div>
                <p style={{ color: "var(--t3)", fontSize: "0.78rem" }}>
                  Each point = one agent-run optimization cycle
                </p>
              </div>
              <div style={{ display: "flex", gap: "1rem" }}>
                {[{ color: "var(--teal)", label: "Open" }, { color: "var(--gold)", label: "Click" }].map(l => (
                  <div key={l.label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <div style={{ width: 8, height: 2, background: l.color, borderRadius: 1 }} />
                    <span className="label">{l.label}</span>
                  </div>
                ))}
              </div>
            </div>
            {historyData.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={historyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="cycle" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
                  <YAxis unit="%" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} domain={[0, 100]} />
                  <Tooltip content={<ChartTip />} />
                  <Line type="monotone" dataKey="Open Rate" stroke="var(--teal)" strokeWidth={2} dot={{ r: 4, fill: "var(--teal)" }} activeDot={{ r: 6 }} />
                  <Line type="monotone" dataKey="Click Rate" stroke="var(--gold)" strokeWidth={2} dot={{ r: 4, fill: "var(--gold)" }} activeDot={{ r: 6 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : campaign.status === "awaiting_approval" ? (
              <div style={{ height: 180, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "0.75rem" }}>
                <div style={{ fontSize: "1.5rem" }}>⚡</div>
                <div className="font-display" style={{ fontWeight: 700, fontSize: "0.95rem" }}>
                  Optimized Campaign Ready for Review
                </div>
                <p style={{ color: "var(--t3)", fontSize: "0.78rem", textAlign: "center", maxWidth: 360 }}>
                  The AI agent has optimized the campaign based on performance data. Approve the new version to continue.
                </p>
                <button className="btn btn-gold btn-sm" onClick={() => navigate(`/approve/${id}`)}>
                  Review & Approve →
                </button>
              </div>
            ) : (
              <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t3)", fontSize: "0.83rem", fontStyle: "italic" }}>
                <span className="cursor" style={{ marginRight: 8 }} />
                {campaign.status === "running" ? "Campaign is executing — results will appear shortly…" : "Waiting for campaign execution…"}
              </div>
            )}
          </div>

          {/* Campaign brief */}
          <div className="card" style={{ padding: "1.25rem" }}>
            <div className="label" style={{ marginBottom: "0.75rem" }}>Campaign Brief</div>
            <p style={{ color: "var(--t2)", fontSize: "0.875rem", lineHeight: 1.7 }}>{campaign.brief}</p>
          </div>
        </div>
      )}

      {/* Tab: Segments */}
      {tab === "segments" && (
        <div className="anim-in">
          <div className="card" style={{ padding: "1.5rem", marginBottom: "1rem" }}>
            <div className="label" style={{ marginBottom: "1.25rem" }}>Performance by Customer Segment</div>
            {segData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={segData} barGap={4}>
                  <XAxis dataKey="segment" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
                  <YAxis unit="%" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
                  <Bar dataKey="Open Rate" fill="var(--teal)" radius={[3,3,0,0]} maxBarSize={28} />
                  <Bar dataKey="Click Rate" fill="var(--gold)" radius={[3,3,0,0]} maxBarSize={28} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ height: 180, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t3)", fontSize: "0.83rem", fontStyle: "italic" }}>
                Segment data will appear after campaign execution
              </div>
            )}
          </div>

          {segments.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
              {segments.map((seg: any, i: number) => {
                const ids = new Set(seg.customer_ids || [])
                const rows = rawData.filter(r => ids.has(r.customer_id))
                const total = rows.length || 1
                const openPct = Math.round(rows.filter(r => r.EO === "Y").length / total * 100)
                const clickPct = Math.round(rows.filter(r => r.EC === "Y").length / total * 100)
                return (
                  <div key={i} className="card" style={{ padding: "1rem 1.25rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: "0.875rem" }}>{seg.name || `Segment ${i+1}`}</div>
                        {seg.targeting_rationale && (
                          <p style={{ color: "var(--t3)", fontSize: "0.75rem", marginTop: 3 }}>{seg.targeting_rationale}</p>
                        )}
                      </div>
                      <span className="font-mono" style={{ fontSize: "0.65rem", color: "var(--t3)", flexShrink: 0, marginLeft: "1rem" }}>
                        {(seg.size || ids.size).toLocaleString()} customers
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: "1.5rem" }}>
                      {[{ label: "Open", pct: openPct, color: "var(--teal)" }, { label: "Click", pct: clickPct, color: "var(--gold)" }].map(m => (
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
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Tab: A/B */}
      {tab === "ab" && (
        <div className="anim-in">
          <div className="card" style={{ padding: "1.5rem", marginBottom: "1rem" }}>
            <div className="label" style={{ marginBottom: "1.25rem" }}>A/B Variant Performance</div>
            {abData.length > 0 ? (
              <ResponsiveContainer width="100%" height={Math.max(180, abData.length * 75)}>
                <BarChart data={abData} layout="vertical" barGap={4}>
                  <XAxis type="number" unit="%" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="variant" width={110} tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
                  <Bar dataKey="Open Rate" fill="var(--teal)" radius={[0,3,3,0]} maxBarSize={22} />
                  <Bar dataKey="Click Rate" fill="var(--gold)" radius={[0,3,3,0]} maxBarSize={22} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ height: 120, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t3)", fontSize: "0.83rem", fontStyle: "italic" }}>
                A/B data will appear after campaign execution
              </div>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
            {emails.map((email: any, i: number) => {
              const colors = ["var(--gold)", "var(--teal)", "var(--purple)", "var(--orange)"]
              const ac = colors[i % colors.length]
              return (
                <div key={i} className="email-card" style={{ borderTop: `2px solid ${ac}` }}>
                  <div className="email-header">
                    <span style={{ fontFamily: "Syne", fontWeight: 700, fontSize: "0.68rem", letterSpacing: "0.07em", textTransform: "uppercase", color: ac, background: `${ac}12`, border: `1px solid ${ac}28`, padding: "3px 8px", borderRadius: 5 }}>
                      {email.variant?.replace("_", " ") || `Variant ${i+1}`}
                    </span>
                    <span style={{ color: "var(--t1)", fontWeight: 600, fontSize: "0.875rem", flex: 1, marginLeft: "0.75rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {email.subject}
                    </span>
                    <span className="font-mono" style={{ fontSize: "0.65rem", color: "var(--t3)", flexShrink: 0, marginLeft: "0.75rem" }}>
                      {(email.customer_ids?.length || 0).toLocaleString()} recipients
                    </span>
                  </div>
                  <div className="email-body">{email.body}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Tab: AI Insights */}
      {tab === "analysis" && (
        <div className="anim-in">
          <div className="card card-accent" style={{ padding: "1.5rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1.25rem" }}>
              <div style={{
                width: 36, height: 36, borderRadius: 8,
                background: "rgba(245,200,66,0.1)",
                border: "1px solid rgba(245,200,66,0.2)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "1.1rem", flexShrink: 0
              }}>🤖</div>
              <div>
                <div className="font-display" style={{ fontWeight: 700, fontSize: "0.95rem" }}>AI Agent Analysis</div>
                <div className="label" style={{ marginTop: 2 }}>Monitor · Optimizer insights</div>
              </div>
            </div>
            <div className="divider" style={{ marginBottom: "1.25rem" }} />
            {analysis ? (
              <div style={{ color: "var(--t2)", fontSize: "0.9rem", lineHeight: 1.85, whiteSpace: "pre-wrap" }}>
                {analysis}
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", color: "var(--t3)", fontStyle: "italic", fontSize: "0.875rem" }}>
                <span className="cursor" />
                Agent is still analyzing performance data…
              </div>
            )}
          </div>

          {latestReport && (
            <div className="card" style={{ padding: "1.25rem", marginTop: "1rem" }}>
              <div className="label" style={{ marginBottom: "0.85rem" }}>Latest Report Summary</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                {[
                  { label: "Total Rows",  value: latestReport.raw_report?.total_rows || 0 },
                  { label: "Fetched At",  value: latestReport.fetched_at?.slice(0, 16) || "—" },
                  { label: "Open Rate",   value: `${latestOpen}%` },
                  { label: "Click Rate",  value: `${latestClick}%` },
                ].map(m => (
                  <div key={m.label} style={{ padding: "0.75rem", background: "var(--card2)", borderRadius: 8 }}>
                    <div className="label" style={{ marginBottom: 4 }}>{m.label}</div>
                    <div className="font-mono" style={{ fontSize: "0.875rem", color: "var(--t1)" }}>{m.value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}