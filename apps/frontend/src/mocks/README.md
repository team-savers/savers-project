# mocks/

This directory contains **synthetic demo fixtures only**. The SAVERS
repository is public, so every persona, name, phone number, and address
here is **a fictional placeholder** — no real person is represented.

- Phone numbers use the obvious dummy range `010-0000-xxxx`.
- Names are common Korean given names chosen for readability, not to
  identify anyone.
- Addresses use real administrative subdivisions (관악구 서원동 etc.) so the
  demo plausibly exercises the 행정동/법정동 code mapping, but the building
  numbers are illustrative.
- All disaster-response source excerpts in `chatReplies.ts` are paraphrased
  patterns, **not** official 행정안전부 국민행동요령 text. Real retrieval is
  served by `apps/ai-engine` from the actual corpus.

If you need a fixture that looks like real PII, stop — design the schema
shape instead and let the backend populate it from real, encrypted storage.
