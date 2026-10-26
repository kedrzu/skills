# Cases

One feature: record a website visitor's tracking-consent decisions so they can be proven later.
It was designed and planned, then built over five days, and went through three rounds of review.
Each piece below looked reasonable when it was proposed. An open-ended review that asked only
"what here is over-engineered?" traced most of the system to the first three premises. The
redesign that followed replaced all of it with one object write per record.

## A pattern borrowed together with its reason

**Proposed:** consent records are delivered through a streaming service that batches them into
storage. The design took this from the audit log, which already worked that way, and lifted it
into a shared infrastructure helper so both could use it.

**The premise:** the audit log batches because it writes a lot. Consent is written a few times per
visitor. Nobody measured the consent volume. The reason was carried over with the pattern, and
nobody checked it.

**Simpler:** one conditional object write per record (write only if the key does not exist yet),
which also gives idempotency at no extra cost. **Gives up:** nothing anyone had asked for.

**Pattern:** reusing a mechanism is not the same as following a pattern when the mechanism is
generalised to do it. Ask what justified it where it came from.

## A number nobody stated

**Proposed:** keep every record for 7.5 years, in storage locked against deletion, with a role
allowed to lift the lock and a pipeline that audits every deletion.

**The premise:** the retention period was picked by analogy with another kind of record. No law and
no counsel stated it for consent records. The lock, the role that could lift it, and the deletion
audit all existed to serve that number.

**Simpler:** the retention the actual requirement needs, under a lock nobody can lift. With a
shorter period that fits the real obligation, the lifting role and the deletion audit have nothing
left to do. **Gives up:** records older than the real obligation needs.

**Pattern:** one invented number can carry a whole subsystem. When the premise falls, everything
that served it falls with it, so look for what depends on a premise before judging its cost.

## Recording what has not changed

**Proposed:** every visit re-records a visitor's standing opt-out, so there is always fresh
evidence of it.

**The premise:** that a decision needs re-proving while it stands. Nobody asked for that. A decision
is proven by the record made when it was taken.

**Simpler:** record a decision when it is made or changed. **Gives up:** nothing.

## A model taken from a vendor

**Proposed:** a new consent ID on every change, plus a separate withdrawal record linking the old ID
to the new one.

**The premise:** it came from an argument about how a commercial consent product models consent,
not from counsel or from anything the feature had to do. A later review also found that a retried
request minted a second ID, so the model had a bug of its own as well as its cost.

**Simpler:** one ID per uninterrupted consent, and a change is a new record under it. **Gives up:**
resemblance to the vendor's model.

**Pattern:** "this is how X does it" is a premise. It holds only if the reason X does it applies
here.

## A fix that grows the system

**Proposed during review fixes:** answers to compliance findings that were each sensible on their
own: a signed choice cookie with a rotating key set, the liftable lock above, and a separate
account-wide audit-trail stack.

**The premise:** each finding was answered by adding a mechanism. Nobody asked whether the finding
needed one, or whether a change to something that already existed would do.

**Simpler:** most findings were answered by the redesign above. Once the store's premises were cut,
there was nothing left to sign, unlock or audit. **Gives up:** nothing that survived the redesign.

**Pattern:** a review fix that adds a new mechanism is a small design decision made in the middle
of a fix. Ask before building it.
