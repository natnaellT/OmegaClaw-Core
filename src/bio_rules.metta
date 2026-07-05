; ===========================================================================
; Bio-Claw Axioms (Auto-Generated)
; Generated at: 2026-06-21T19:32:03.591632Z
; Grounded strictly in the Biolink Model and the active BioCypher schema.
; ===========================================================================

; predicate: biolink:affects
(Similarity biolink:affects biolink:affects)

; predicate: biolink:enables
(Similarity biolink:enables biolink:enables)
(= (biolink:enables $a $b) (biolink:has participant $b $a))

; predicate: biolink:overlaps
(Similarity biolink:overlaps biolink:overlaps)

; predicate: biolink:regulates
(Similarity biolink:regulates biolink:regulates)
