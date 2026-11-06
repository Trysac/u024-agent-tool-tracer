# Project record

## Objective

Trace every tool call of an agent with redacted arguments, results, timing, cost and errors to JSONL, and render runs as escaped Mermaid sequence diagrams

## Scope

- In scope: the public API documented in [README.md](../README.md), typed and tested.
- Out of scope: anything that needs runtime dependencies or I/O without an accepted ADR.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 701214 / 104843 |
| Hours (human) | pending measurement |
| Cost (USD) | 1.0070 |

## Factory run u024 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2385 | 82622 | 0 | 4246 | 0.4159 |
| fix-1 | claude-sonnet-5-5 | no | 4 | 632 | 6323 | 24719 | 0.0246 |
| fix-2 | claude-sonnet-5-5 | no | 6 | 1173 | 10265 | 45153 | 0.0419 |
| fix-3 | claude-sonnet-5-5 | no | 8 | 895 | 6542 | 55027 | 0.0308 |
| audit | claude-sonnet-5-5 | no | 14 | 5742 | 52557 | 174776 | 0.2063 |
| fix-4 | claude-sonnet-5-5 | no | 14 | 6343 | 18607 | 145634 | 0.1245 |
| fix-1 | claude-sonnet-5-5 | no | 8 | 1613 | 11164 | 63180 | 0.0504 |
| fix-2 | claude-sonnet-5-5 | no | 8 | 1194 | 7705 | 58244 | 0.0370 |
| docs | claude-haiku-5-5 | no | 127788 | 4629 | 0 | 0 | 0.0755 |

Total: $1.0070. Prices: Anthropic list prices.
