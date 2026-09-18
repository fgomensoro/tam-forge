# Northstar Commerce Case

Use this same case throughout Month 1 so every exercise compounds instead of resetting context.

## Customer
Northstar Retail is an enterprise omnichannel retailer. It processes approximately 50,000 orders per month and plans a major product launch in six weeks.

## Systems
- Storefront and marketplace channels send orders to your integration platform.
- Your platform creates orders in the ERP.
- A payment processor sends asynchronous payment webhooks.
- The ERP sends fulfillment requests to a third-party logistics provider.
- Finance reconciles processor settlement reports against orders and payouts.

## Constraints
- ERP limit: 1,000 requests per minute.
- ERP write requests sometimes complete even when the client times out.
- Webhooks are delivered at least once and can arrive out of order.
- OAuth access tokens expire; refresh tokens can be revoked.
- The ERP has no native idempotency-key support.
- A failed order can block fulfillment and create manual finance work.

## Stakeholders
- Integration engineer: wants exact technical evidence.
- Operations lead: cares about order backlog and manual work.
- VP Engineering: cares about reliability, launch risk, and ownership.
- CFO: cares about duplicate charges, missing settlements, and financial exposure.

## Success metrics
- 99.5% of valid orders reach ERP within five minutes.
- No duplicate financial operations.
- Unmatched financial records are detected within 30 minutes.
- Customer receives an incident update every 30 minutes during a SEV-1.

## Scenario cards
1. The customer says “your API is down,” but platform monitoring is green.
2. ERP order creation times out; a retry creates a duplicate order.
3. Payment webhooks arrive twice and out of order.
4. ERP begins returning 429 responses during launch traffic.
5. OAuth refresh starts returning `invalid_grant` for one account.
6. Ten percent of payments fail the day before launch; Engineering estimates two weeks for a permanent fix.
7. Finance finds captured payments with no corresponding settlement record.
8. Sales promised a feature that Product has not approved.
9. Operations wants a two-minute API timeout instead of changing a slow sequential process.
10. The customer renews in six months but uses only two of six available products.
