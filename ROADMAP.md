# Hatlas — design roadmap

What to design next, in order. Tick a box when its Figma frames are ready; I build from the frames.
Each item says what the screen needs to show and whether the data for it already exists.

## Done (designed and built)
- [x] Main page: map, quick-access menu, usage card
- [x] Search: results, "more", nothing found, "İşletmeci misiniz?"
- [x] "Bu veritabanının düzeltilmeye ihtiyacı var" banner
- [x] Sign-in prompt before contributing ("Desktop - 8")
- [x] Choosing the kind of change: Güncelle / Düzenle / Bildir ("Desktop - 9")
- [~] Stop page ("Desktop - 5/6"): designed, not built yet; see step 3

## Before the Reddit launch

### 1. Line panel (left column when a line is open)
Search lands on lines more than anything else, and today a line shows only on the map.
- Line number and name, operator (with logo if any), city
- Direction switch (gidiş / dönüş)
- Stops in order, each tappable (opens the stop); first and last stop marked
- The "broken route" state for lines like Kocaeli 44001
- "Ulaşım verisi olarak indir" and "Düzenleme öner", as on the stop page
- Data: ready (lines, directions, stops per line; four cities have no stops per line: show the line without the list)

### 2. City panel (left column when a city or operator is open)
The "health check" part of Hatlas: what makes it more than a map.
- City name, plate badge, province (for districts like Alanya)
- Numbers: lines, stops, operators
- Feed status: valid until (and "expired"), broken lines count, stops-per-line yes/no
- Source and licence line ("kk-gtfs, KentKart verisinden, CC0")
- Operator list (tap one to filter the map), "Bütün veriyi indir"
- Data: ready (catalog.json has all of it)

### 3. Stop page, final version
Your frames exist; decide on the open points before I build it:
- Accessibility as facts (asansör / rampa / hissedilebilir yüzey: var / yok / bilinmiyor), not a 1-10 score
- Ratings with "N kişi" and a minimum before a score shows
- Stop ID without the line code (TR_41_11052), plus the source GTFS stop_id
- The map popup: keep it, or let the left panel be enough
- Data: ready for name, lines through the stop, coordinates; ratings and photos need the contribution backend

### 4. "Hatlas GTFS Açık Veri Koleksiyonu"
The catalogue page: why developers come and cite us.
- One card or row per city: status, valid until, lines/stops, last update, download (GTFS zip / JSON)
- Licence and citation line, link to the source project
- Data: ready

### 5. "Acilen güncelleme gerektiren yerler"
A list of what needs fixing, so contributors know where to start.
- Cities with expired feeds or no lines; lines with broken routes (46 in Sivas, 14 in Muğla…)
- Each row opens the line or city on the map
- Data: ready (the broken-route check already runs in the build)

### 6. About, legal and operators
Needed before anyone outside sees it.
- Hakkında: what Hatlas is, how the checks work, sources, "Açık kaynak katkıları" (credits: kk-gtfs, OpenStreetMap, OpenFreeMap, MapLibre, Haskoy)
- Gizlilik (KVKK): what is stored for contributors, the usage statistics, map tiles from OpenFreeMap
- The operator page behind "İşletmeci misiniz?": verify with an official e-mail, send official data, logo choices, removal
- Footer with the "bağımsız proje, işletmecilerle bağlantısı yoktur" line
- Data: text only

### 7. Phone versions
Most Reddit visitors open links on a phone; today the phone layout is my provisional stacked version.
- Main page (map full screen, menu and panels as a bottom sheet), search, line/city/stop panels, sign-in

## After sign-in works (Avar ID app registration + deploy)

### 8. The three contribution flows
- **Güncelle:** editing on the map: move/delete/add a stop, redraw a route segment; a summary before sending
- **Düzenle:** forms: rename a stop, accessibility facts, timetable entry
- **Bildir:** maintenance or announcement with date range, source link and photo (the photo rules: no faces or plates)
- A "sent, waiting for review" confirmation for each

### 9. Account and review
- Avatar menu: profile, "Katkılarım" (status of each: bekliyor / kabul / ret), sign out
- Your review queue: accept / reject / edit a contribution, see who sent it

## Later
- **Son değişiklikler:** a feed of data updates and accepted contributions (needs the review flow first)
- **En yakın toplu taşıma hatları:** the result list after "use my location" (today it only centres the map)
- **Erişilebilir Seyahat Asistanı:** needs a concept first. What should it do? (step-free routes? stops with elevators? audio guidance?)
- States: loading, map tiles failed, data failed, 404
