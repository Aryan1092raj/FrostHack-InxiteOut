import { useState, useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { approveCampaign, rejectCampaign, getCampaign } from "../lib/api"

export default function ApprovalScreen() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [campaign, setCampaign] = useState<any>(null)
  const [showReject, setShowReject] = useState(false)
  const [rejectNote, setRejectNote] = useState("")
  const [approving, setApproving] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [activeVariant, setActiveVariant] = useState(0)

  useEffect(() => { getCampaign(id!).then(setCampaign) }, [id])

  if (!campaign) return (
    <div className="page-narrow" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "60vh" }}>
      <div className="font-mono" style={{ color: "var(--t3)", fontSize: "0.8rem" }}>
        Loading campaign<span className="cursor" />
      </div>
    </div>
  )

  const emails: any[] = campaign.emails || []
  const strategy = campaign.strategy || {}
  const segments: any[] = strategy.segments || []
  const totalCustomers = emails.reduce((s: number, e: any) => s + (e.customer_ids?.length || 0), 0)

  const handleApprove = async () => {
    setApproving(true)
    try {
      await approveCampaign(id!)
      navigate(`/reports/${id}`)
    } catch {
      setApproving(false)
    }
  }

  const handleReject = async () => {
    setRejecting(true)
    try {
      await rejectCampaign(id!, rejectNote)
      navigate(`/new?campaign_id=${id}&note=${encodeURIComponent(rejectNote)}`)
    } catch {
      setRejecting(false)
    }
  }

  const variantColors = ["var(--gold)", "var(--teal)", "var(--purple)", "var(--orange)"]

  return (
    <div className="page-narrow">

      {/* Header */}
      <div className="anim-up" style={{ marginBottom: "2rem" }}>
        <button className="back-link" style={{ marginBottom: "1.5rem" }} onClick={() => navigate("/")}>
          ← Dashboard
        </button>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
          <div>
            <div className="label" style={{ marginBottom: 6 }}>Human-in-Loop Approval</div>
            <h1 className="font-display" style={{ fontSize: "1.9rem", fontWeight: 800, letterSpacing: "-0.025em" }}>
              Review Campaign
            </h1>
            <p style={{ color: "var(--t3)", fontSize: "0.83rem", marginTop: 5 }}>
              #{id!.slice(0, 8)} · Approve to schedule or reject with feedback
            </p>
          </div>
          <span className="badge badge-awaiting" style={{ marginTop: 6, flexShrink: 0 }}>Awaiting Approval</span>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="anim-up delay-1" style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: "0.85rem", marginBottom: "1.75rem" }}>
        {[
          { label: "Email Variants", value: emails.length, color: "var(--gold)" },
          { label: "Segments", value: segments.length, color: "var(--teal)" },
          { label: "Customers", value: totalCustomers.toLocaleString(), color: "var(--purple)" },
        ].map(s => (
          <div key={s.label} className="stat">
            <div className="label" style={{ marginBottom: 8 }}>{s.label}</div>
            <div className="font-display" style={{ fontSize: "1.6rem", fontWeight: 800, color: s.color }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Variant tabs */}
      {emails.length > 1 && (
        <div className="anim-up delay-1" style={{ marginBottom: "1rem" }}>
          <div className="tab-bar" style={{ display: "inline-flex" }}>
            {emails.map((e: any, i: number) => (
              <button key={i} className={`tab ${activeVariant === i ? "active" : ""}`}
                      onClick={() => setActiveVariant(i)}>
                {e.variant?.replace("_", " ") || `Variant ${i + 1}`}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Email Cards */}
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem", marginBottom: "1.75rem" }}>
        {(emails.length > 1 ? [emails[activeVariant]] : emails).map((email: any, i: number) => {
          const varIdx = emails.length > 1 ? activeVariant : i
          const accentColor = variantColors[varIdx % variantColors.length]
          const sendTime = strategy.send_times?.[varIdx] || strategy.send_times?.[0] || "TBD"
          return (
            <div key={i} className="email-card anim-up delay-2"
                 style={{ borderTop: `2px solid ${accentColor}` }}>
              <div className="email-header">
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flex: 1, minWidth: 0 }}>
                  <span style={{
                    fontFamily: "Syne", fontWeight: 700, fontSize: "0.7rem",
                    letterSpacing: "0.07em", textTransform: "uppercase",
                    color: accentColor,
                    background: `${accentColor}14`,
                    border: `1px solid ${accentColor}30`,
                    padding: "3px 8px", borderRadius: 5
                  }}>
                    {email.variant?.replace("_", " ") || `Variant ${varIdx + 1}`}
                  </span>
                  <span style={{ color: "var(--t1)", fontWeight: 600, fontSize: "0.875rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {email.subject || "No subject"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: "1.25rem", flexShrink: 0, alignItems: "center" }}>
                  <div style={{ textAlign: "right" }}>
                    <div className="label">Recipients</div>
                    <div className="font-mono" style={{ fontSize: "0.78rem", color: accentColor, marginTop: 2 }}>
                      {(email.customer_ids?.length || 0).toLocaleString()}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="label">Send Time</div>
                    <div className="font-mono" style={{ fontSize: "0.7rem", color: "var(--t2)", marginTop: 2 }}>
                      {sendTime}
                    </div>
                  </div>
                </div>
              </div>

              <div className="email-body">
                {email.body || "No body content"}
              </div>
            </div>
          )
        })}
      </div>

      {/* Strategy Overview */}
      {segments.length > 0 && (
        <div className="card anim-up delay-2" style={{ padding: "1.25rem", marginBottom: "1.75rem" }}>
          <div className="label" style={{ marginBottom: "0.85rem" }}>Segment Targeting</div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {segments.slice(0, 4).map((seg: any, i: number) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.6rem 0", borderBottom: i < segments.length - 1 ? "1px solid var(--border)" : "none" }}>
                <div>
                  <span style={{ color: "var(--t1)", fontSize: "0.83rem", fontWeight: 500 }}>{seg.name || `Segment ${i + 1}`}</span>
                  {seg.targeting_rationale && (
                    <p style={{ color: "var(--t3)", fontSize: "0.75rem", marginTop: 2 }}>
                      {seg.targeting_rationale.slice(0, 80)}
                    </p>
                  )}
                </div>
                <div style={{ display: "flex", gap: "1rem", flexShrink: 0, alignItems: "center" }}>
                  {seg.optimal_send_time && (
                    <span className="font-mono" style={{ fontSize: "0.65rem", color: "var(--teal)", background: "rgba(45,212,191,0.08)", border: "1px solid rgba(45,212,191,0.18)", padding: "2px 7px", borderRadius: 4 }}>
                      {seg.optimal_send_time}
                    </span>
                  )}
                  <span className="font-mono" style={{ fontSize: "0.7rem", color: "var(--t3)" }}>
                    {(seg.size || seg.customer_ids?.length || 0).toLocaleString()} customers
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action Zone */}
      {!showReject ? (
        <div className="anim-up delay-3" style={{ display: "flex", gap: "0.85rem" }}>
          <button className="btn btn-green" style={{ flex: 1, justifyContent: "center", padding: "1rem" }}
                  onClick={handleApprove} disabled={approving}>
            {approving ? "Scheduling…" : "✓ Approve & Schedule Campaign"}
          </button>
          <button className="btn btn-red" style={{ flex: 1, justifyContent: "center", padding: "1rem" }}
                  onClick={() => setShowReject(true)}>
            ✕ Reject & Re-plan
          </button>
        </div>
      ) : (
        <div className="card anim-up" style={{ padding: "1.5rem", borderColor: "rgba(248,113,113,0.2)" }}>
          <div className="label" style={{ marginBottom: "0.75rem", color: "var(--red)" }}>
            Feedback for Agent Re-plan
          </div>
          <textarea className="input" style={{ height: 110 }}
            placeholder='e.g. "Make tone more formal. Only target customers 35+. Move send time to 8–9 PM IST."'
            value={rejectNote}
            onChange={e => setRejectNote(e.target.value)}
          />
          <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.85rem" }}>
            <button className="btn btn-red" style={{ flex: 1, justifyContent: "center" }}
                    onClick={handleReject} disabled={rejecting || !rejectNote.trim()}>
              {rejecting ? "Sending…" : "Send Feedback & Re-plan"}
            </button>
            <button className="btn btn-ghost" onClick={() => setShowReject(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
