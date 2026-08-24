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
| ~~citizensinformation.ie~~ | **Retrieved 24 August 2026.** See below |
| gov.ie operational guidelines for social welfare in IPAS accommodation | HTTP 403 |
| irishimmigration.ie work rights page | HTTP 404 at the URL in the design |

Under ADR-0005 an unverified source cannot be cited, so every task that would
have depended on those pages is absent. That is the rule working rather than
failing: the corpus is smaller and honest instead of larger and hopeful.

**The citizensinformation.ie block was half a moved URL.** The 403 was real, and
it is still real for a bare HTTP client. But the address in the design also
404s now: the page moved from `claiming-a-social-welfare-payment/` to
`social-assistance-payments/`, and read in a browser at its current address it
returns normally. Recorded here because "403" was carried for a week as a
settled fact about the publisher when half of it was a stale link on our side,
and a source declared unreachable stops being retried.

Two things it carries that nothing else in this corpus did:

**Asylum seekers are not regarded as habitually resident.** Stated plainly by
the publisher. It is the single most consequential sentence in this corpus for
the people this system is for, and it was absent. It does not turn the habitual
residence condition into something this system decides, and `child_benefit.apply`
still names it as a determination: who counts as an asylum seeker, when that
stops applying, and what somebody's status is on a given day are all judgements
made by a Deciding Officer.

**A social welfare appeal has a 60 day window.** Also absent. The appeal task
said the clock starts on the date of the letter without saying how long the
clock runs, which for a system whose whole premise is that getting the timing
right matters was the wrong kind of gap.

The Habitual Residence Condition itself was already modelled, against Crosscare
Migrant Project. This paragraph used to say it was not, which was true when it
was written and stopped being true without the paragraph being updated.

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

- Retrieve the remaining blocked sources by another route, and record a real
  verification. Check the URL before recording a publisher as unreachable: one
  of the three was partly a stale link on our side.
- **Give tasks a deadline, separately from `typical_wait`.** The 60 day appeal
  window is currently a sentence inside `why`, because the task model has no way
  to say "this expires". A wait and a deadline are opposite things: one is time
  you spend, the other is time you lose, and only one of them ends with the door
  shut. For a system about ordering and timing that is a real modelling gap, and
  putting it in prose is a stopgap rather than a fix.
- Expand to roughly forty tasks, including education and banking.
- Give `accommodation.move_in` something to produce so that being housed reads
  as done rather than as no longer applicable.
- Have the whole thing reviewed by somebody who has navigated this process, or
  by an NGO worker. That review is the highest-value check available here and
  no amount of testing substitutes for it.
