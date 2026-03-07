import { useState, useEffect, useRef } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { startCampaign } from "../lib/api"

interface AgentEvent { agent: string; message: string; type: string }

const AGENTS: Record<string, { color: string; icon: string; label: string }> = {
  profiler:     { color: "#a78bfa", icon: "◈", label: "Profiler" },
  strategist:   { color: "#fb923c", icon: "◉", label: "Strategist" },
  content_gen:  { color: "#4ade80", icon: "◎", label: "Content" },
  executor:     { color: "#f5c842", icon: "▶", label: "Executor" },
  monitor:      { color: "#2dd4bf", icon: "◐", label: "Monitor" },
  optimizer:    { color: "#f472b6", icon: "◈", label: "Optimizer" },
  orchestrator: { color: "#8b9cc8", icon: "◇", label: "Orch." },
}

const PIPELINE = ["profiler", "strategist", "content_gen", "executor", "monitor", "optimizer"]

const EXAMPLE = `Run email campaign for launching XDeposit, a flagship term deposit product from SuperBFSI, that gives 1 percentage point higher returns than its competitors. Announce an additional 0.25 percentage point higher returns for female senior citizens. Optimise for open rate and click rate. Don't skip emails to customers marked 'inactive'. Include the call to action: https://superbfsi.com/xdeposit/explore/`

export default function NewCampaign() {
  const [brief, setBrief] = useState("")
  const [campaignId, setCampaignId] = useState<string | null>(null)
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [approvalReady, setApprovalReady] = useState(false)
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)
  const [activeAgent, setActiveAgent] = useState<string | null>(null)
  const termRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const note = params.get("note")
  const replanId = params.get("campaign_id")

  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight
  }, [events])

  useEffect(() => {
    if (replanId) { setCampaignId(replanId); connect(replanId) }
  }, [replanId])

  const connect = (id: string) => {
    const base = import.meta.env.VITE_API_URL || "http://localhost:8000"
    const es = new EventSource(`${base}/api/campaign/${id}/stream`)
    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data)
        if (ev.type === "ping" || ev.type === "connected") return
        setEvents(p => [...p, ev])
        if (ev.agent) setActiveAgent(ev.agent)
        if (ev.type === "approval_needed") { setApprovalReady(true); setActiveAgent(null); es.close() }
        else if (ev.type === "done") { setDone(true); setActiveAgent(null); es.close() }
        else if (ev.type === "error") { setActiveAgent(null); es.close() }
      } catch (_) {}
    }
    es.onerror = () => { setActiveAgent(null); es.close() }
  }

  const launch = async () => {
    if (!brief.trim()) return
    setLoading(true); setEvents([]); setApprovalReady(false); setDone(false); setActiveAgent(null)
    const res = await startCampaign(brief)
    setCampaignId(res.campaign_id)
    setLoading(false)
    connect(res.campaign_id)
  }

  const completedAgents = new Set(events.map(e => e.agent))

  return (
    <div className="page-narrow">

      {/* Header */}
      <div className="anim-up" style={{ marginBottom: "2rem" }}>
        <button className="back-link" style={{ marginBottom: "1.5rem" }} onClick={() => navigate("/")}>
          ← Dashboard
        </button>
        <div className="label" style={{ marginBottom: 6 }}>AI Campaign Builder</div>
        <h1 className="font-display" style={{ fontSize: "1.9rem", fontWeight: 800, letterSpacing: "-0.025em" }}>
          {campaignId ? "Agent Pipeline" : "New Campaign"}
        </h1>
        <p style={{ color: "var(--t3)", fontSize: "0.83rem", marginTop: 5 }}>
          {campaignId ? `Campaign · ${campaignId.slice(0, 8)}` : "Describe your campaign in plain English — AI handles the rest"}
        </p>
      </div>

      {/* Re-plan note */}
      {note && (
        <div className="anim-up delay-1" style={{
          background: "rgba(251,146,60,0.05)",
          border: "1px solid rgba(251,146,60,0.18)",
          borderRadius: 10,
          padding: "0.9rem 1.1rem",
          marginBottom: "1.5rem",
          display: "flex", gap: "0.75rem", alignItems: "flex-start"
        }}>
          <span style={{ color: "var(--orange)", marginTop: 1 }}>↺</span>
          <div>
            <div className="font-display" style={{ fontWeight: 700, color: "var(--orange)", fontSize: "0.8rem" }}>
              Re-planning with your feedback
            </div>
            <p style={{ color: "var(--t3)", fontSize: "0.78rem", marginTop: 3, fontStyle: "italic" }}>
              "{note}"
            </p>
          </div>
        </div>
      )}

      {/* Brief input */}
      {!campaignId && (
        <div className="anim-up delay-1">
          <div className="card card-accent card-glow" style={{ padding: "1.5rem", marginBottom: "1rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
              <span className="label">Campaign Brief</span>
              <button onClick={() => setBrief(EXAMPLE)} style={{
                fontFamily: "JetBrains Mono", fontSize: "0.6rem", color: "var(--gold)",
                background: "rgba(245,200,66,0.07)", border: "1px solid rgba(245,200,66,0.18)",
                borderRadius: 5, padding: "3px 9px", cursor: "pointer", letterSpacing: "0.05em"
              }}>
                Use Example
              </button>
            </div>
            <textarea className="input" style={{ height: 165 }}
              placeholder='e.g. "Run email campaign for launching XDeposit, a flagship term deposit from SuperBFSI, that gives 1 percentage point higher returns..."'
              value={brief}
              onChange={e => setBrief(e.target.value)}
            />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1rem" }}>
              <span className="font-mono" style={{ fontSize: "0.65rem", color: brief.length > 900 ? "var(--red)" : "var(--t3)" }}>
                {brief.length} chars
              </span>
              <button className="btn btn-gold" onClick={launch} disabled={loading || !brief.trim()} style={{ minWidth: 175 }}>
                {loading ? "Initializing…" : "▶ Launch AI Agents"}
              </button>
            </div>
          </div>

          {/* Pipeline preview */}
          <div className="card" style={{ padding: "1rem 1.25rem" }}>
            <div className="label" style={{ marginBottom: "0.7rem" }}>Agent Pipeline</div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", overflowX: "auto", paddingBottom: 2 }}>
              {PIPELINE.map((ag, i) => {
                const cfg = AGENTS[ag]
                return (
                  <div key={ag} style={{ display: "flex", alignItems: "center", gap: "0.4rem", flexShrink: 0 }}>
                    <div style={{
                      display: "flex", alignItems: "center", gap: 5,
                      background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)",
                      borderRadius: 7, padding: "5px 10px"
                    }}>
                      <span style={{ color: cfg.color, fontSize: "0.8rem" }}>{cfg.icon}</span>
                      <span className="font-mono" style={{ fontSize: "0.65rem", color: "var(--t3)" }}>{cfg.label}</span>
                    </div>
                    {i < PIPELINE.length - 1 && (
                      <span style={{ color: "var(--t4)", fontSize: "0.7rem" }}>›</span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* Live stream */}
      {campaignId && (
        <div className="anim-in">

          {/* Pipeline status bar */}
          <div className="card" style={{ padding: "0.85rem 1.25rem", marginBottom: "1rem", overflowX: "auto" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              {PIPELINE.map((ag, i) => {
                const cfg = AGENTS[ag]
                const isActive = activeAgent === ag
                const isDone = completedAgents.has(ag) && !isActive
                return (
                  <div key={ag} style={{ display: "flex", alignItems: "center", gap: "0.4rem", flexShrink: 0 }}>
                    <div style={{
                      display: "flex", alignItems: "center", gap: 5,
                      padding: "4px 10px", borderRadius: 6,
                      background: isActive ? `${cfg.color}14` : isDone ? "rgba(74,222,128,0.07)" : "transparent",
                      border: isActive ? `1px solid ${cfg.color}35` : isDone ? "1px solid rgba(74,222,128,0.18)" : "1px solid transparent",
                      transition: "all 0.25s"
                    }}>
                      <span style={{ fontSize: "0.75rem", color: isActive ? cfg.color : isDone ? "var(--green)" : "var(--t4)" }}>
                        {isDone ? "✓" : cfg.icon}
                      </span>
                      <span className="font-mono" style={{
                        fontSize: "0.63rem",
                        color: isActive ? cfg.color : isDone ? "var(--green)" : "var(--t4)"
                      }}>
                        {cfg.label}
                      </span>
                      {isActive && <span className="cursor" style={{ width: 5, height: 10 }} />}
                    </div>
                    {i < PIPELINE.length - 1 && (
                      <span style={{ color: "var(--t4)", fontSize: "0.6rem" }}>›</span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Terminal */}
          <div className="terminal" style={{ height: 400, marginBottom: "1rem" }}>
            {/* Terminal chrome */}
            <div className="terminal-header">
              <div className="terminal-dot" style={{ background: "#ff5f57" }} />
              <div className="terminal-dot" style={{ background: "#febc2e" }} />
              <div className="terminal-dot" style={{ background: "#28c840" }} />
              <span className="font-mono" style={{ marginLeft: 8, fontSize: "0.65rem", color: "var(--t3)" }}>
                agent-stream — {campaignId.slice(0, 8)}…
              </span>
              <span className="font-mono" style={{ marginLeft: "auto", fontSize: "0.6rem", color: "var(--t4)" }}>
                {events.length} events
              </span>
            </div>

            <div className="terminal-body" ref={termRef} style={{ height: "calc(100% - 44px)", overflowY: "auto" }}>
              {events.length === 0 ? (
                <span style={{ color: "var(--t3)" }}>$ initializing agent pipeline<span className="cursor" /></span>
              ) : (
                events.map((e, i) => {
                  const cfg = AGENTS[e.agent] || AGENTS.orchestrator
                  const msgColor = e.type === "error" ? "var(--red)"
                    : e.type === "action" ? "var(--gold)"
                    : e.type === "approval_needed" ? "var(--green)"
                    : e.type === "done" ? "var(--green)"
                    : "var(--t2)"
                  return (
                    <div key={i} style={{ display: "flex", gap: "0.6rem", marginBottom: "0.2rem" }}>
                      <span style={{ color: cfg.color, flexShrink: 0, minWidth: 72 }}>[{cfg.label.toLowerCase()}]</span>
                      <span style={{ color: msgColor, lineHeight: 1.65 }}>{e.message}</span>
                    </div>
                  )
                })
              )}
              {activeAgent && (
                <div style={{ display: "flex", gap: "0.6rem", marginTop: "0.2rem" }}>
                  <span style={{ color: AGENTS[activeAgent]?.color || "var(--t3)", minWidth: 72 }}>
                    [{AGENTS[activeAgent]?.label.toLowerCase() || activeAgent}]
                  </span>
                  <span style={{ color: "var(--t3)" }}>thinking<span className="cursor" /></span>
                </div>
              )}
            </div>
          </div>

          {/* Approval CTA */}
          {approvalReady && (
            <div className="card card-accent card-glow anim-up" style={{ padding: "1.35rem 1.5rem", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem" }}>
              <div>
                <div className="font-display" style={{ fontWeight: 700, color: "var(--gold)", fontSize: "0.95rem", marginBottom: 4 }}>
                  ✅ Campaign Ready for Review
                </div>
                <p style={{ color: "var(--t3)", fontSize: "0.83rem" }}>
                  AI agents have prepared emails and selected customer segments.
                </p>
              </div>
              <button className="btn btn-gold" style={{ flexShrink: 0 }}
                      onClick={() => navigate(`/approve/${campaignId}`)}>
                Review & Approve →
              </button>
            </div>
          )}

          {done && !approvalReady && (
            <div className="card anim-up" style={{ padding: "1.35rem 1.5rem", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "1rem", borderColor: "rgba(74,222,128,0.2)" }}>
              <div>
                <div className="font-display" style={{ fontWeight: 700, color: "var(--green)", fontSize: "0.95rem", marginBottom: 4 }}>
                  ✓ Pipeline Complete
                </div>
                <p style={{ color: "var(--t3)", fontSize: "0.83rem" }}>All optimization cycles finished successfully.</p>
              </div>
              <button className="btn btn-ghost" onClick={() => navigate(`/reports/${campaignId}`)}>
                View Report →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
