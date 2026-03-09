import { useEffect, useState } from "react"
import { getCampaigns } from "../lib/api"
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, RadarChart, Radar,
  PolarGrid, PolarAngleAxis, LineChart, Line
} from "recharts"

interface Campaign {
  id: string
  status: string
  brief: string
  metrics: { open_rate: number; click_rate: number; total_sent: number }
  created_at: string
  iteration: number
  strategy?: { segments?: any[] }
  emails?: any[]
}

const ChartTip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      {label && <p style={{ color: "var(--t3)", marginBottom: 6 }}>{label}</p>}
      {payload.map((p: any) => (
        <p key={p.name || p.dataKey} style={{ color: p.color || p.stroke || "var(--gold)", margin: "2px 0" }}>
          {p.name || p.dataKey}: <strong>{typeof p.value === "number" ? `${p.value.toFixed(1)}%` : p.value}</strong>
        </p>
      ))}
    </div>
  )
}

export default function Analysis() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getCampaigns().then(d => { setCampaigns(d as Campaign[]); setLoading(false) })
  }, [])

  const done = campaigns.filter(c => c.status === "done" || c.metrics.total_sent > 0)
  const totalSent = done.reduce((s, c) => s + (c.metrics.total_sent || 0), 0)
  const avgOpen = done.length ? done.reduce((s, c) => s + c.metrics.open_rate, 0) / done.length * 100 : 0
  const avgClick = done.length ? done.reduce((s, c) => s + c.metrics.click_rate, 0) / done.length * 100 : 0
  const best = done.reduce((b, c) => c.metrics.click_rate > (b?.metrics.click_rate || 0) ? c : b, null as Campaign | null)
  const avgIter = done.length ? done.reduce((s, c) => s + (c.iteration || 1), 0) / done.length : 0

  // Per-campaign performance chart
  const perfData = done.map((c, i) => ({
    name: `C${i + 1}`,
    "Open Rate": +(c.metrics.open_rate * 100).toFixed(1),
    "Click Rate": +(c.metrics.click_rate * 100).toFixed(1),
    sent: c.metrics.total_sent,
  }))

  // Trend over time (ordered by created_at)
  const sorted = [...done].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
  const trendData = sorted.map((c, i) => ({
    run: `Run ${i + 1}`,
    "Open Rate": +(c.metrics.open_rate * 100).toFixed(1),
    "Click Rate": +(c.metrics.click_rate * 100).toFixed(1),
  }))

  // Efficiency score = weighted 70% click + 30% open
  const effData = done.map((c, i) => ({
    name: `C${i + 1}`,
    score: +(c.metrics.click_rate * 70 + c.metrics.open_rate * 30).toFixed(1),
    id: c.id,
  })).sort((a, b) => b.score - a.score)

  // Radar: avg metrics profile
  const radarData = [
    { metric: "Open Rate", value: +avgOpen.toFixed(1), full: 100 },
    { metric: "Click Rate", value: +avgClick.toFixed(1), full: 100 },
    { metric: "Coverage", value: done.length > 0 ? Math.min(100, totalSent / 50) : 0, full: 100 }, // 100% = 5000 emails (full cohort size)
    { metric: "Iterations", value: Math.min(100, avgIter * 25), full: 100 },
    { metric: "Completion", value: done.length > 0 ? (done.length / campaigns.length) * 100 : 0, full: 100 },
  ]

  if (loading) return (
    <div className="page" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "60vh" }}>
      <span className="font-mono" style={{ color: "var(--t3)", fontSize: "0.8rem" }}>
        Loading analysis<span className="cursor" />
      </span>
    </div>
  )

  if (done.length === 0) return (
    <div className="page">
      <div className="anim-up" style={{ marginBottom: "2rem" }}>
        <div className="label" style={{ marginBottom: 6 }}>Aggregate Intelligence</div>
        <h1 className="font-display" style={{ fontSize: "1.9rem", fontWeight: 800, letterSpacing: "-0.025em" }}>Analysis</h1>
      </div>
      <div className="card" style={{ padding: "4rem", textAlign: "center" }}>
        <div style={{ fontSize: "2.5rem", marginBottom: "0.75rem" }}>📊</div>
        <div className="font-display" style={{ fontWeight: 700, marginBottom: 6 }}>No data yet</div>
        <p style={{ color: "var(--t3)", fontSize: "0.83rem" }}>Run your first campaign to see aggregated analysis here.</p>
      </div>
    </div>
  )

  return (
    <div className="page">

      {/* Header */}
      <div className="anim-up" style={{ marginBottom: "2rem" }}>
        <div className="label" style={{ marginBottom: 6 }}>Aggregate Intelligence</div>
        <h1 className="font-display" style={{ fontSize: "1.9rem", fontWeight: 800, letterSpacing: "-0.025em" }}>
          Analysis
        </h1>
        <p style={{ color: "var(--t3)", fontSize: "0.83rem", marginTop: 5 }}>
          Cross-campaign performance insights across {done.length} completed run{done.length !== 1 ? "s" : ""}
        </p>
      </div>

      {/* KPIs */}
      <div className="anim-up delay-1" style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: "0.85rem", marginBottom: "1.75rem" }}>
        {[
          { label: "Campaigns Run", value: done.length, unit: "", color: "var(--purple)" },
          { label: "Avg Open Rate", value: avgOpen.toFixed(1), unit: "%", color: "var(--teal)" },
          { label: "Avg Click Rate", value: avgClick.toFixed(1), unit: "%", color: "var(--gold)" },
          { label: "Total Emails", value: totalSent.toLocaleString(), unit: "", color: "var(--green)" },
          { label: "Avg Iterations", value: avgIter.toFixed(1), unit: "x", color: "var(--orange)" },
        ].map(s => (
          <div key={s.label} className="stat">
            <div className="label" style={{ marginBottom: 8 }}>{s.label}</div>
            <div className="font-display" style={{ fontSize: "1.5rem", fontWeight: 800, color: s.color, lineHeight: 1 }}>
              {s.value}{s.unit}
            </div>
          </div>
        ))}
      </div>

      {/* Charts row 1 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.25rem", marginBottom: "1.25rem" }}>

        {/* Per-campaign bar */}
        <div className="card anim-up delay-2" style={{ padding: "1.25rem" }}>
          <div className="label" style={{ marginBottom: "1rem" }}>Performance per Campaign</div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={perfData} barGap={3}>
              <XAxis dataKey="name" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
              <YAxis unit="%" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
              <Bar dataKey="Open Rate" fill="var(--teal)" radius={[3,3,0,0]} maxBarSize={24} />
              <Bar dataKey="Click Rate" fill="var(--gold)" radius={[3,3,0,0]} maxBarSize={24} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Trend line */}
        <div className="card anim-up delay-2" style={{ padding: "1.25rem" }}>
          <div className="label" style={{ marginBottom: "1rem" }}>Performance Trend Over Time</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trendData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="run" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} />
              <YAxis unit="%" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} axisLine={false} tickLine={false} domain={[0,100]} />
              <Tooltip content={<ChartTip />} />
              <Line type="monotone" dataKey="Open Rate" stroke="var(--teal)" strokeWidth={2} dot={{ r: 4, fill: "var(--teal)" }} />
              <Line type="monotone" dataKey="Click Rate" stroke="var(--gold)" strokeWidth={2} dot={{ r: 4, fill: "var(--gold)" }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Charts row 2 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.25rem", marginBottom: "1.25rem" }}>

        {/* Efficiency leaderboard */}
        <div className="card anim-up delay-3" style={{ padding: "1.25rem" }}>
          <div className="label" style={{ marginBottom: "1rem" }}>
            Efficiency Score
            <span style={{ fontFamily: "'DM Sans', sans-serif", fontWeight: 400, color: "var(--t4)", textTransform: "none", letterSpacing: 0, marginLeft: 6 }}>
              (70% click + 30% open)
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            {effData.slice(0, 6).map((d, i) => (
              <div key={d.id} style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                <span className="font-mono" style={{ fontSize: "0.65rem", color: i === 0 ? "var(--gold)" : "var(--t4)", width: 20, flexShrink: 0 }}>
                  #{i + 1}
                </span>
                <span className="font-mono" style={{ fontSize: "0.65rem", color: "var(--t3)", width: 60, flexShrink: 0 }}>
                  {d.name}
                </span>
                <div style={{ flex: 1 }}>
                  <div className="prog-track">
                    <div className="prog-fill" style={{
                      width: `${d.score}%`,
                      background: i === 0 ? "var(--gold)" : i === 1 ? "var(--teal)" : "var(--purple)",
                    }} />
                  </div>
                </div>
                <span className="font-mono" style={{ fontSize: "0.68rem", color: i === 0 ? "var(--gold)" : "var(--t2)", width: 40, textAlign: "right", flexShrink: 0 }}>
                  {d.score}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Radar */}
        <div className="card anim-up delay-3" style={{ padding: "1.25rem" }}>
          <div className="label" style={{ marginBottom: "0.5rem" }}>Campaign Health Radar</div>
          <ResponsiveContainer width="100%" height={220}>
            <RadarChart data={radarData} margin={{ top: 10, right: 30, bottom: 10, left: 30 }}>
              <PolarGrid stroke="rgba(255,255,255,0.07)" />
              <PolarAngleAxis dataKey="metric" tick={{ fontFamily: "JetBrains Mono", fontSize: 10, fill: "var(--t3)" }} />
              <Radar name="Score" dataKey="value" stroke="var(--gold)" fill="var(--gold)" fillOpacity={0.12} strokeWidth={1.5} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Best performer highlight */}
      {best && (
        <div className="card card-accent anim-up delay-3" style={{ padding: "1.25rem" }}>
          <div className="label" style={{ marginBottom: "0.75rem" }}>🏆 Best Performing Campaign</div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "2rem" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ color: "var(--t2)", fontSize: "0.875rem", lineHeight: 1.65 }}>
                {best.brief.slice(0, 160)}…
              </p>
              <div className="font-mono" style={{ fontSize: "0.6rem", color: "var(--t4)", marginTop: 6 }}>
                #{best.id.slice(0, 8)}
              </div>
            </div>
            <div style={{ display: "flex", gap: "2rem", flexShrink: 0 }}>
              {[
                { label: "Open Rate", val: (best.metrics.open_rate * 100).toFixed(1) + "%", color: "var(--teal)" },
                { label: "Click Rate", val: (best.metrics.click_rate * 100).toFixed(1) + "%", color: "var(--gold)" },
              ].map(m => (
                <div key={m.label} style={{ textAlign: "center" }}>
                  <div className="label" style={{ marginBottom: 4 }}>{m.label}</div>
                  <div className="font-display" style={{ fontSize: "1.5rem", fontWeight: 800, color: m.color }}>{m.val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
