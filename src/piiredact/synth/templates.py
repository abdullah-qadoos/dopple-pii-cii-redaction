"""Free-text templates, hard-case vocabulary and decoys. All values are generated, never real."""

# {person} {person_lower} {initials} {email} {mailto} {phone} {org} {address} {card} {iban}
# {ssn} {url} {domain} are PII; {order_id} {bad_card} {product} {city} {placeholder} {date}
# {uuid} are decoys that must NOT be detected.
TEMPLATES = [
    "Spoke with {person} from {org} about the renewal; call back on {phone}.",
    "Customer {person} reported card {card} was charged twice on {date}.",
    "Send the contract to {email} and cc {person}.",
    "Wire refund to IBAN {iban} for order {order_id}.",
    "Shipping to {address}. Contact: {phone}.",
    "{person} (SSN {ssn}) requested a copy of their file.",
    "See profile at {url}; product {product} shipped from {city}.",
    "Escalated by {person_lower} - ref {uuid}.",
    "Meeting notes: {initials} and {person} agreed on pricing with {org}.",
    "Reach me at {mailto} or {phone}.",
    "Invoice {order_id} for {org}, total paid with {card}.",
    "New hire {person} starts {date}; badge mailed to {address}.",
    "Placeholder contact {placeholder} should be ignored; real one is {email}.",
    "Test card {bad_card} declined, retried with {card}.",
    "{org} moved their site to {domain}.",
    "Left voicemail for {person} at {phone}, no answer.",
    "Account holder {person}, IBAN {iban}, branch in {city}.",
    # --- below: only in the test split, never seen while tuning on dev ---
    "Forwarded ticket from {email} to {person_lower} at {org}.",
    "{person} asked us to delete records for {initials} by {date}.",
    "Update billing address for {org} to {address}.",
    "Called {phone} regarding {product}; spoke to {initials}.",
    "Please verify SSN {ssn} for {person} before onboarding.",
    "Our partner {org} ({url}) referred {person}.",
    "Duplicate payment: card {card}, order {order_id}, uuid {uuid}.",
]
DEV_TEMPLATES = 17

PRODUCTS = ["Widget Pro 3000", "Model X-200 Router", "UltraClean Mop", "Gizmo Max", "Aero Desk Lamp", "Quantum Blender"]  # fmt: skip
PLACEHOLDERS = ["test@example", "user@domain", "[REDACTED]", "xxx-xxx-xxxx"]
COMMON_WORD_ORGS = ["Summit", "Beacon", "Harbor", "Pinnacle", "Evergreen", "Keystone"]
US_AREAS = ["212", "312", "415", "617", "713", "206", "303", "404", "512", "646"]
