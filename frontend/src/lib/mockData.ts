export const MOCK_CAMPAIGNS = [
  {
    id: "uuid-001",
    status: "awaiting_approval",
    brief: "Run email campaign for XDeposit, a flagship term deposit product from SuperBFSI.",
    strategy: {
      segments: [
        ["CUST001", "CUST002", "CUST003"],
        ["CUST004", "CUST005"]
      ],
      send_times: ["04:03:26 09:00:00", "04:03:26 18:00:00"],
      ab_variants: ["variant_a", "variant_b"]
    },
    emails: [
      {
        variant: "variant_a",
        subject: "Grow Your Savings with XDeposit 💰",
        body: "Dear Customer,\n\nWe are excited to introduce XDeposit — a term deposit that gives you 1% higher returns than competitors.\n\nFor female senior citizens, we offer an additional 0.25% higher returns.\n\nExplore now: https://superbfsi.com/xdeposit/explore/",
        customer_ids: ["CUST001", "CUST002", "CUST003"]
      },
      {
        variant: "variant_b",
        subject: "Your Money Deserves More — Try XDeposit!",
        body: "Hi there! 👋\n\nXDeposit gives you returns that beat the market by 1 full percentage point.\n\nSpecial bonus for female senior citizens: extra 0.25% returns! 🎉\n\nCheck it out: https://superbfsi.com/xdeposit/explore/",
        customer_ids: ["CUST004", "CUST005"]
      }
    ],
    metrics: {
      open_rate: 0.42,
      click_rate: 0.18,
      total_sent: 5
    },
    created_at: "2026-03-03T10:00:00Z"
  },
  {
    id: "uuid-002",
    status: "done",
    brief: "Follow-up campaign targeting inactive customers with a re-engagement offer.",
    strategy: {
      segments: [
        ["CUST006", "CUST007"]
      ],
      send_times: ["03:03:26 10:00:00"],
      ab_variants: ["variant_a"]
    },
    emails: [
      {
        variant: "variant_a",
        subject: "We Miss You! Special Offer Inside",
        body: "Dear Customer,\n\nWe noticed you haven't been active recently.\n\nHere is a special offer just for you — XDeposit now gives 1% higher returns than competitors.\n\nDon't miss out: https://superbfsi.com/xdeposit/explore/",
        customer_ids: ["CUST006", "CUST007"]
      }
    ],
    metrics: {
      open_rate: 0.28,
      click_rate: 0.09,
      total_sent: 2
    },
    created_at: "2026-03-02T08:00:00Z"
  }
]