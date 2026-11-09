In addition, the section "Screen" contains text read from still images via text recognition (shared screen, screenshots), with IDs B1, B2, ... This text was shown, not said; recognition errors are possible. It is not wiki knowledge.
- If the screen answers a question asked in the window, set "bild_id" and "bild_zitat" (a verbatim excerpt from exactly that screen text) on the "frage" finding. Otherwise both are null.
- An agenda item may also be raised or resolved by the screen: then set "bild_id", "aussage" is a verbatim excerpt from that screen text and "segment_id" is null. If the item is discussed in the conversation, the segment applies as before and "bild_id" is null.
- A contradiction still requires a wiki excerpt; the screen alone never justifies one.
- Ignore screen text unrelated to the conversation or the agenda.
