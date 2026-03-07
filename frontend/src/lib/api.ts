

// =====================================================
// IMPORTANT: This file is the ONLY place that talks
// to the backend. All pages import from here.
//
// RIGHT NOW: Every function returns mock (fake) data
// DAY 6: You'll swap mock data for real fetch() calls
// =====================================================

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000"

// ---------------------------
// Get all campaigns
// ---------------------------
export const getCampaigns = async () => {
  const res = await fetch(`${BASE_URL}/api/campaigns`)
  const data = await res.json()
  return data.campaigns.map((c: any) => ({
    ...c,
    metrics: c.metrics || { open_rate: 0, click_rate: 0, total_sent: 0 }
  }))
}

// ---------------------------
// Get one campaign by its ID
// ---------------------------
export const getCampaign = async (id: string) => {
  const res = await fetch(`${BASE_URL}/api/campaign/${id}`)
  return res.json()
}

// ---------------------------
// Start a new campaign
// ---------------------------
export const startCampaign = async (brief: string) => {
  const res = await fetch(`${BASE_URL}/api/campaign/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief })
  })
  return res.json()
}

// ---------------------------
// Approve a campaign
// ---------------------------
export const approveCampaign = async (id: string) => {
  const res = await fetch(`${BASE_URL}/api/campaign/${id}/approve`, {
    method: "POST"
  })
  return res.json()
}

// ---------------------------
// Reject a campaign with feedback
// ---------------------------
export const rejectCampaign = async (id: string, note: string) => {
  const res = await fetch(`${BASE_URL}/api/campaign/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: note })
  })
  return res.json()
}

// ---------------------------
// Get performance report
// ---------------------------
export const getCampaignReport = async (id: string) => {
  const res = await fetch(`${BASE_URL}/api/campaign/${id}/report`)
  return res.json()
}

// ---------------------------
// Get report history (for charts)
// ---------------------------
export const getCampaignReports = async (id: string) => {
  const res = await fetch(`${BASE_URL}/api/campaign/${id}/reports`)
  const data = await res.json()
  return data.reports || []
}
