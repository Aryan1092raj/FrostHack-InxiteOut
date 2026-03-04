import { MOCK_CAMPAIGNS } from "./mockData"

// =====================================================
// IMPORTANT: This file is the ONLY place that talks
// to the backend. All pages import from here.
//
// RIGHT NOW: Every function returns mock (fake) data
// DAY 6: You'll swap mock data for real fetch() calls
// =====================================================

const BASE_URL = "http://localhost:8000"

// ---------------------------
// Get all campaigns
// ---------------------------
export const getCampaigns = async () => {
  // Mock version — returns fake data immediately
  return MOCK_CAMPAIGNS

  // DAY 6 — swap to this:
  // const res = await fetch(`${BASE_URL}/api/campaigns`)
  // return res.json()
}

// ---------------------------
// Get one campaign by its ID
// ---------------------------
export const getCampaign = async (id: string) => {
  // Mock version — finds the campaign with matching id
  const found = MOCK_CAMPAIGNS.find(c => c.id === id)
  return found || MOCK_CAMPAIGNS[0]  // fallback to first if not found

  // DAY 6 — swap to this:
  // const res = await fetch(`${BASE_URL}/api/campaign/${id}`)
  // return res.json()
}

// ---------------------------
// Start a new campaign
// ---------------------------
export const startCampaign = async (brief: string) => {
  // Mock version — pretends a campaign was created and returns an ID
  console.log("Brief received:", brief)
  return { id: "uuid-001" }

  // DAY 6 — swap to this:
  // const res = await fetch(`${BASE_URL}/api/campaign/start`, {
  //   method: "POST",
  //   headers: { "Content-Type": "application/json" },
  //   body: JSON.stringify({ brief })
  // })
  // return res.json()
}

// ---------------------------
// Approve a campaign
// ---------------------------
export const approveCampaign = async (id: string) => {
  // Mock version — pretends approval was sent
  console.log("Campaign approved:", id)
  return { success: true }

  // DAY 6 — swap to this:
  // const res = await fetch(`${BASE_URL}/api/campaign/${id}/approve`, {
  //   method: "POST"
  // })
  // return res.json()
}

// ---------------------------
// Reject a campaign with feedback
// ---------------------------
export const rejectCampaign = async (id: string, note: string) => {
  // Mock version — pretends rejection was sent
  console.log("Campaign rejected:", id, "| Reason:", note)
  return { success: true, note }

  // DAY 6 — swap to this:
  // const res = await fetch(`${BASE_URL}/api/campaign/${id}/reject`, {
  //   method: "POST",
  //   headers: { "Content-Type": "application/json" },
  //   body: JSON.stringify({ note })
  // })
  // return res.json()
}

// ---------------------------
// Get performance report
// ---------------------------
export const getCampaignReport = async (id: string) => {
  // Mock version — returns the metrics of the matching campaign
  const found = MOCK_CAMPAIGNS.find(c => c.id === id)
  return found ? found.metrics : MOCK_CAMPAIGNS[0].metrics

  // DAY 6 — swap to this:
  // const res = await fetch(`${BASE_URL}/api/campaign/${id}/report`)
  // return res.json()
}
