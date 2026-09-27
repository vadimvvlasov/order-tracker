# Incident 20260927T025225Z-order-tracker-5xx-responses

- Status: **recovered**
- Alert: Order Tracker 5xx responses (firing), endpoint `/api/orders/{order_id}`
- Summary: Users get 5xx responses from GET /api/orders/{order_id}
- Dashboard: http://localhost:3000/d/order-tracker?from=1790473940000&orgId=1&to=1790477545010
- Deployed version(s): dev
- Agent: `claude` model `claude-opus-5-5`, 10 turns, 42.5 s, exit 0
- Permission denials: 0
- Agent action: **fixed**
- Root cause (agent): order_detail computed express delivery with placed_at.replace(day=placed_at.day + 2), which raises ValueError for orders placed in the last two days of a month (seeded express-1002 is dated at the previous month's end).
- Fix (agent): app/main.py - use placed_at + timedelta(days=2); tests/test_api.py - added month-end express regression test and seeded express-1002 endpoint test
- Verification (responder): `verify-recovery.sh /api/orders/express-1002` exit 0

## Files

- `alert.json` raw webhook, `evidence.md` / `evidence.json` what the agent saw
- `prompt.md` exact task, `transcript.jsonl` full agent session, `response.md` final answer
- `fix.diff` agent's change left for human review (only if it changed app/ or tests/)
- `baseline.diff` changes that were already uncommitted before the agent ran, if any
- `incident.json` timeline

## Timeline

- 2026-09-27T02:52:25+00:00 received: firing alert Order Tracker 5xx responses for /api/orders/{order_id}
- 2026-09-27T02:52:25+00:00 evidence_collected: 3 error logs, 1 error traces, failing paths ['/api/orders/express-1002']
- 2026-09-27T02:52:25+00:00 agent_running: claude headless, allowlist of 11 tools
- 2026-09-27T02:53:07+00:00 agent_done: action=fixed exit=0
- 2026-09-27T02:53:07+00:00 recovered: failing paths no longer return 5xx; fix awaits human review
