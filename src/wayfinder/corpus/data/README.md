# Seed corpus: Ireland

**This is a portfolio project, not a service, and this corpus is not advice.**
It is a small, deliberately partial set of tasks used to demonstrate a planning
engine. Anybody who actually needs help with the international protection
process in Ireland should go to the organisations named in the sources, not to
this. See [`docs/10-risk-and-ethics.md`](../../../../docs/10-risk-and-ethics.md).

## What is here

Ten tasks across four domains, every one cited to a source that was fetched and
read on 18 August 2026.

## What is not here, and why

Three of the sources the design proposed could not be retrieved when the corpus
was built:

| Source | Result |
|---|---|
| citizensinformation.ie | HTTP 403 |
| gov.ie operational guidelines for social welfare in IPAS accommodation | HTTP 403 |
| irishimmigration.ie work rights page | HTTP 404 at the URL in the design |

Under ADR-0005 an unverified source cannot be cited, so every task that would
have depended on those pages is absent. That is the rule working rather than
failing: the corpus is smaller and honest instead of larger and hopeful.

The most visible consequence is that **the Habitual Residence Condition is not
modelled.** It is the canonical determination in this domain and the example
used throughout the design, and the pages describing it are exactly the ones
that could not be fetched. Adding it from memory would be inventing content,
which is the one thing this corpus must never contain.

Education and banking have no tasks at all for the same reason. The domains
exist in the model; the content does not exist yet.

## Deliberate omissions

No amounts, rates or thresholds appear in any task. They change most often and
are precisely what people plan around, so a stale figure does more damage than a
missing one. Tasks say a payment exists and where to ask about it.

No task asserts what anybody is entitled to.

## Known modelling weaknesses in this seed

`accommodation.move_in` and `ipas.request_accommodation` are gated on
`accommodation` not being `ipas`, so once somebody is housed they leave the plan
as "no longer applicable" rather than as "done". That is the wrong shape: they
were completed, not made irrelevant. Fixing it properly means giving the move-in
task an artefact to produce, which is a content decision for M2 rather than a
patch here. The replanning output words this carefully in the meantime.

## What M2 has to do

- Retrieve the blocked sources by another route, and record a real verification.
- Model the Habitual Residence Condition once there is a source for it.
- Expand to roughly forty tasks, including education and banking.
- Give `accommodation.move_in` something to produce so that being housed reads
  as done rather than as no longer applicable.
- Have the whole thing reviewed by somebody who has navigated this process, or
  by an NGO worker. That review is the highest-value check available here and
  no amount of testing substitutes for it.
