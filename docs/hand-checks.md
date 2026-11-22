# Hand checks of the sample data

| Date | City | Place | Field | Source says | Reality | How checked | Result |
|---|---|---|---|---|---|---|---|
| 18 Nov | Matera | Casa Noha | address | Recinto Canove, 9 (OSM via Geoapify) | Recinto Cavone, 9 | Google Maps search | ❌ typo in the source |
| 18 Nov | Matera | Casa Noha | months | 2–10 | Feb–Oct | official opening hours | ✅ |
| 18 Nov | Lisbon | Jerónimos Monastery | price | €18 pp | €18 regular ticket; reduced options exist | opened source link | ✅ (ticket type not shown) |
| 18 Nov | Lisbon | Belém Tower | price | €15 pp | €15 regular ticket; reduced options exist | opened source link | ✅ (ticket type not shown) |
| 18 Nov | Lisbon | Museu do Fado | price | €5 pp | €5 regular ticket; reduced options exist | opened source link | ✅ (ticket type not shown) |
| 18 Nov | Lisbon | MAAT | price | €16 pp | €16 regular, non-resident; cheaper for Portugal residents | opened source link | ✅ (correct for a tourist, but not stated) |
| 18 Nov | Lisbon | Alfama Food Tour | price | €93 pp | €93 on the operator's site | opened source link | ✅ |
| 19 Nov | Lisbon | Museu de Lisboa – Torreão Poente | open/closed | suggested as a normal experience (demo, OSM via Geoapify) | the source says "Encerrado temporariamente" (temporarily closed) | read the card | ❌ closed place suggested: no check for "closed" |
| 19 Nov | Lisbon | Castelo de S. Jorge skip-the-line (Viator) | price, label, rating | €31 pp · Adult (26–64) · 4.71/5, 619 reviews | same on the Viator page | opened Viator link | ✅ |
| 19 Nov | Lisbon | Belém Tower exterior tour (Viator) | price, label, rating | €30 pp · Adult (25–64) · 4.79/5, 19 reviews | same on the Viator page | opened Viator link | ✅ |
| 19 Nov | Lisbon | Banksy Museum ticket (Viator) | price, label, rating | €13 pp · Adult (18–64) · 4.67/5, 49 reviews | same on the Viator page | opened Viator link | ✅ |
| 19 Nov | London | Frameless (Viator) | price, label, rating | £29.50 (€35.39) pp · Adult (18–100) · 4.73/5, 4,190 reviews | same on the Viator page | opened Viator link | ✅ |
| 19 Nov | London | Royal Albert Hall tour (Viator) | price, label, rating | £20 (€23.99) pp · Adult (17–59) · 4.74/5, 311 reviews | same on the Viator page | opened Viator link | ✅ |
| 19 Nov | London | VIP Bicester Village trip (Viator) | price per group | £899.56 (€1,079.11) per group | same on the Viator page, price for the whole group | opened Viator link | ✅ per-group fix works |
| 19 Nov | Matera | Underground mattress / Hypogeum Materasum (Viator) | price, label, rating | €8 pp · Adult (1–99) · 4.53/5, 92 reviews | same on the Viator page | opened Viator link | ✅ |
| 19 Nov | Matera | Hypogeum Materasum | duplicate | appears twice: Viator item + Geoapify "Ipogeo MateraSum" | same place | compared names and links | ❌ duplicate in the list |
| 22 Nov | Rome | Colosseum guided tour (Viator) | price, label | €130 pp · Adult (13–99) · verified | same on the Viator page | opened Viator link | ✅ (verified) |
| 22 Nov | Rome | Pasta & tiramisu cooking class (Viator) | price, label | €99 pp · Adult (18–99) · verified | same on the Viator page | opened Viator link | ✅ (verified) |
| 22 Nov | Rome | Pizza, gelato & supplì class (Viator) | price, label | €99 pp · Adult (18–100) · verified | same on the Viator page | opened Viator link | ✅ (verified) |
| 22 Nov | Rome | Private Colosseum photoshoot (Viator) | price, label | €45 pp · Adult (13–99), when 2 book together · verified | same on the Viator page | opened Viator link | ✅ (verified) |
| 22 Nov | Rome | Capitoline Museums | fact in suggestion | "free on Sunday 6 Dec" written in the suggestion text, not checked by code or verifier | not checked yet | read the card | ⚠️ finding: facts can slip into suggestion text |