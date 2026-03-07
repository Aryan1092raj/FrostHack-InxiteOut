import { BrowserRouter, Routes, Route, NavLink, useNavigate, useLocation } from "react-router-dom"
import { useState, useEffect } from "react"
import Dashboard from "./pages/Dashboard"
import NewCampaign from "./pages/NewCampaign"
import ApprovalScreen from "./pages/ApprovalScreen"
import Reports from "./pages/Reports"
import History from "./pages/History"
import Analysis from "./pages/Analysis"
import { getCampaigns } from "./lib/api"

function NavItem({ to, icon, label, badge, exact }: {
  to: string; icon: string; label: string; badge?: number; exact?: boolean
}) {
  return (
    <NavLink
      to={to}
      end={exact}
      style={({ isActive }: { isActive: boolean }) => ({
        display: "flex",
        alignItems: "center",
        gap: "0.65rem",
        padding: "0.55rem 0.8rem",
        borderRadius: 8,
        textDecoration: "none",
        transition: "all 0.15s",
        background: isActive ? "rgba(245,200,66,0.07)" : "transparent",
        border: isActive ? "1px solid rgba(245,200,66,0.15)" : "1px solid transparent",
        position: "relative",
        overflow: "hidden",
      })}
    >
      {({ isActive }: { isActive: boolean }) => (
        <>
          {isActive && (
            <span style={{
              position: "absolute", left: 0, top: "20%", height: "60%",
              width: 2.5, background: "var(--gold)", borderRadius: "0 2px 2px 0",
            }} />
          )}
          <span style={{ fontSize: "0.9rem", lineHeight: 1, opacity: isActive ? 1 : 0.45, flexShrink: 0 }}>
            {icon}
          </span>
          <span style={{
            fontFamily: "'Syne', sans-serif",
            fontWeight: 600,
            fontSize: "0.76rem",
            letterSpacing: "0.02em",
            color: isActive ? "var(--gold)" : "#7a8fb0",
            transition: "color 0.15s",
            flex: 1,
          }}>
            {label}
          </span>
          {badge != null && badge > 0 && (
            <span style={{
              background: "var(--gold)", color: "#080a0f",
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "0.58rem", fontWeight: 700,
              borderRadius: 99, padding: "1px 5px",
              minWidth: 16, textAlign: "center",
            }}>
              {badge}
            </span>
          )}
        </>
      )}
    </NavLink>
  )
}

function Sidebar({ pendingCount }: { pendingCount: number }) {
  const navigate = useNavigate()
  return (
    <aside style={{
      width: 210,
      minHeight: "100vh",
      background: "#0c1628",
      borderRight: "1px solid rgba(255,255,255,0.1)",
      display: "flex",
      flexDirection: "column",
      position: "fixed",
      top: 0, left: 0, bottom: 0,
      zIndex: 50,
      padding: "1.25rem 0.75rem",
    }}>
      {/* Logo */}
      <div style={{ padding: "0 0.4rem", marginBottom: "1.75rem" }}>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "0.55rem", fontWeight: 600,
          letterSpacing: "0.15em", textTransform: "uppercase",
          color: "#4a5d80", marginBottom: 5,
        }}>
          SuperBFSI · XDeposit
        </div>
        <div
          className="font-display"
          onClick={() => navigate("/")}
          style={{
            fontSize: "1.45rem", fontWeight: 800,
            letterSpacing: "-0.025em", lineHeight: 1,
            cursor: "pointer",
          }}
        >
          Campaign<span style={{ color: "var(--gold)" }}>X</span>
        </div>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "0.55rem", color: "#4a5d80", marginTop: 3,
        }}>
          AI Agent v1.0
        </div>
      </div>

      {/* Main nav group */}
      <div style={{ marginBottom: "1.25rem" }}>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "0.53rem", fontWeight: 600,
          letterSpacing: "0.15em", textTransform: "uppercase",
          color: "#5a6e90", padding: "0 0.4rem", marginBottom: "0.45rem",
        }}>
          Main
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
          <NavItem to="/" icon="▦" label="Dashboard" exact />
          <NavItem to="/campaigns" icon="📋" label="Campaigns" badge={pendingCount} />
          <NavItem to="/new" icon="＋" label="New Campaign" />
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: "rgba(255,255,255,0.08)", margin: "0 0.4rem 1.25rem" }} />

      {/* Insights group */}
      <div style={{ marginBottom: "1.25rem" }}>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "0.53rem", fontWeight: 600,
          letterSpacing: "0.15em", textTransform: "uppercase",
          color: "#5a6e90", padding: "0 0.4rem", marginBottom: "0.45rem",
        }}>
          Insights
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
          <NavItem to="/history" icon="🕐" label="History" />
          <NavItem to="/analysis" icon="📊" label="Analysis" />
        </div>
      </div>

      {/* Reports quick link note */}
      <div style={{ padding: "0 0.4rem", marginBottom: "0.75rem" }}>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "0.53rem", fontWeight: 600,
          letterSpacing: "0.15em", textTransform: "uppercase",
          color: "var(--t4)", marginBottom: "0.45rem",
        }}>
          Reports
        </div>
        <div style={{
          fontFamily: "'DM Sans', sans-serif",
          fontSize: "0.72rem", color: "var(--t3)", lineHeight: 1.6,
          padding: "0.5rem 0.65rem",
          background: "rgba(255,255,255,0.02)",
          border: "1px solid var(--border)",
          borderRadius: 7,
        }}>
          Click any campaign in the list to view its detailed report.
        </div>
      </div>

      {/* Pending approval pill */}
      {pendingCount > 0 && (
        <>
          <div style={{ height: 1, background: "var(--border)", margin: "0.5rem 0.4rem 0.75rem" }} />
          <div
            onClick={() => navigate("/campaigns")}
            style={{
              background: "rgba(245,200,66,0.05)",
              border: "1px solid rgba(245,200,66,0.18)",
              borderRadius: 8,
              padding: "0.7rem 0.8rem",
              cursor: "pointer",
              transition: "background 0.15s",
            }}
          >
            <div style={{
              fontFamily: "'Syne', sans-serif",
              fontWeight: 700, fontSize: "0.7rem",
              color: "var(--gold)", marginBottom: 3,
              display: "flex", alignItems: "center", gap: 5,
            }}>
              <span>⚡</span> Needs Approval
            </div>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: "0.62rem", color: "var(--t3)",
            }}>
              {pendingCount} campaign{pendingCount > 1 ? "s" : ""} waiting
            </div>
          </div>
        </>
      )}

      {/* Footer */}
      <div style={{ marginTop: "auto", padding: "0 0.4rem" }}>
        <div style={{ height: 1, background: "rgba(255,255,255,0.08)", marginBottom: "0.85rem" }} />
        <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.58rem", color: "#4a5d80", lineHeight: 1.7 }}>
          FrostHack · XPECTO 2026<br />
          <span>InXiteOut Challenge</span>
        </div>
      </div>
    </aside>
  )
}

function TopBar() {
  const location = useLocation()
  const routeLabel: Record<string, string> = {
    "/": "dashboard",
    "/campaigns": "campaigns",
    "/new": "new-campaign",
    "/history": "history",
    "/analysis": "analysis",
  }
  const label = routeLabel[location.pathname]
    || (location.pathname.startsWith("/approve") ? "approve" : "reports")

  return (
    <div style={{
      position: "sticky", top: 0,
      background: "rgba(7,9,15,0.88)",
      backdropFilter: "blur(18px)",
      borderBottom: "1px solid var(--border)",
      padding: "0.7rem 2rem",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      zIndex: 40,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.63rem", color: "var(--t4)" }}>
          campaignx
        </span>
        <span style={{ color: "var(--t4)", fontSize: "0.65rem" }}>/</span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: "0.63rem", color: "var(--t2)" }}>
          {label}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.85rem" }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 5,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: "0.6rem", color: "var(--green)",
        }}>
          <div style={{
            width: 7, height: 7, borderRadius: "50%",
            background: "var(--green)",
            boxShadow: "0 0 5px rgba(74,222,128,0.6)",
          }} />
          API Online
        </div>
      </div>
    </div>
  )
}

function Layout() {
  const [pendingCount, setPendingCount] = useState(0)

  useEffect(() => {
    const check = () =>
      getCampaigns()
        .then((data: any[]) => setPendingCount(data.filter(c => c.status === "awaiting_approval").length))
        .catch(() => {})
    check()
    const t = setInterval(check, 15000)
    return () => clearInterval(t)
  }, [])

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <Sidebar pendingCount={pendingCount} />
      <main style={{ marginLeft: 210, flex: 1, minHeight: "100vh", background: "var(--bg)" }}>
        <TopBar />
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/campaigns" element={<Dashboard />} />
          <Route path="/new" element={<NewCampaign />} />
          <Route path="/approve/:id" element={<ApprovalScreen />} />
          <Route path="/reports/:id" element={<Reports />} />
          <Route path="/history" element={<History />} />
          <Route path="/analysis" element={<Analysis />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  )
}
