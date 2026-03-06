// ARAM Oracle — Companion Overlay Frontend

(function () {
    "use strict";

    // -- State --
    let ws = null;
    let reconnectDelay = 1000;
    const MAX_RECONNECT = 10000;
    let staticNames = { items: {}, augments: {}, champions: {} };
    let lastResult = null;
    let selectedAugmentIds = [];
    let searchDebounce = null;
    let ocrAvailable = false;
    let scanning = false;

    // -- DOM refs --
    const $ = (id) => document.getElementById(id);
    const connectionDot = $("connection-dot");
    const waitingPanel = $("waiting");
    const champName = $("champion-name");
    const gameTime = $("game-time");
    const goldEl = $("gold");
    const phaseEl = $("phase");
    const augmentList = $("augment-list");
    const rerollBadge = $("reroll-badge");
    const rerollBanner = $("reroll-banner");
    const rerollReason = $("reroll-reason");
    const buildList = $("build-list");
    const buildFooter = $("build-footer");
    const enemyList = $("enemy-list");
    const augmentSearch = $("augment-search");
    const tierFilter = $("tier-filter");
    const searchResults = $("search-results");
    const selectedAugments = $("selected-augments");
    const btnEvaluate = $("btn-evaluate");
    const btnClearInput = $("btn-clear-input");
    const btnScan = $("btn-scan");
    const ocrAutoCheckbox = $("ocr-auto");
    const ocrStatusBadge = $("ocr-status");
    const ocrDetected = $("ocr-detected");
    const augmentConfirm = $("augment-confirm");
    const augmentToast = $("augment-toast");
    const augmentProgress = $("augment-progress");
    let toastTimeout = null;

    // -- Init --

    async function init() {
        await fetchStaticNames();
        await checkOcrStatus();
        connectWebSocket();
        bindSectionToggles();
        bindAugmentInput();
        bindOcrControls();
        bindKeyboard();
    }

    async function fetchStaticNames() {
        try {
            const res = await fetch("/api/static-names");
            staticNames = await res.json();
        } catch (e) {
            console.warn("Failed to fetch static names:", e);
        }
    }

    async function checkOcrStatus() {
        try {
            const res = await fetch("/api/ocr/status");
            const data = await res.json();
            ocrAvailable = data.available;
            updateOcrStatusBadge();
        } catch (e) {
            ocrAvailable = false;
            updateOcrStatusBadge();
        }
    }

    function updateOcrStatusBadge() {
        if (ocrAvailable) {
            ocrStatusBadge.textContent = "OCR";
            ocrStatusBadge.className = "ocr-status-badge ocr-ready";
            ocrStatusBadge.title = "Tesseract OCR ready";
            btnScan.disabled = false;
        } else {
            ocrStatusBadge.textContent = "NO OCR";
            ocrStatusBadge.className = "ocr-status-badge ocr-missing";
            ocrStatusBadge.title = "Tesseract not installed";
            btnScan.disabled = true;
        }
    }

    // -- WebSocket --

    function connectWebSocket() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        ws = new WebSocket(`${proto}//${location.host}/ws/game`);

        ws.onopen = () => {
            reconnectDelay = 1000;
            setConnected(true);
        };

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            handleMessage(msg);
        };

        ws.onclose = () => {
            setConnected(false);
            scheduleReconnect();
        };

        ws.onerror = () => {
            ws.close();
        };
    }

    function scheduleReconnect() {
        setTimeout(() => {
            reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT);
            connectWebSocket();
        }, reconnectDelay);
    }

    function setConnected(connected) {
        connectionDot.className = connected ? "dot connected" : "dot disconnected";
        connectionDot.title = connected ? "Connected" : "Disconnected";
    }

    function wsSend(msg) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(msg));
        }
    }

    // -- Message handling --

    function handleMessage(msg) {
        if (msg.type === "no_game") {
            showWaiting(true);
            return;
        }

        if (msg.type === "update") {
            showWaiting(false);
            lastResult = msg;
            renderUpdate(msg);
            return;
        }

        if (msg.type === "ocr_result") {
            renderOcrResult(msg.detected, msg.augment_choices);
            // Auto-expand augment section if we detected something
            if (msg.detected && msg.detected.length > 0) {
                $("section-augments").classList.remove("collapsed");
                $("section-input").classList.remove("collapsed");
            }
            scanning = false;
            btnScan.textContent = "Scan Screen";
            btnScan.disabled = !ocrAvailable;
            return;
        }

        if (msg.type === "augment_auto_chosen") {
            showAutoChosenToast(msg);
            updateAugmentProgress(msg.augment_state);
            augmentConfirm.classList.add("hidden");
            return;
        }

        if (msg.type === "augment_confirm") {
            showConfirmPanel(msg);
            return;
        }

        if (msg.type === "ack") {
            if (msg.action === "choose_augment") {
                augmentConfirm.classList.add("hidden");
            }
            return;
        }
    }

    function showWaiting(show) {
        waitingPanel.classList.toggle("hidden", !show);

        const sections = ["section-augments", "section-input", "section-build", "section-enemies"];
        sections.forEach((id) => {
            $(id).classList.toggle("hidden", show);
        });
    }

    // -- Render update --

    function renderUpdate(data) {
        renderHeader(data);
        renderRecommendations(data);
        renderBuild(data.build_state);
        renderEnemies(data.enemies || []);
        autoExpandSections(data.phase);
    }

    function renderHeader(data) {
        const bs = data.build_state;
        champName.textContent = bs.champion_name || bs.champion_id || "---";
        phaseEl.textContent = data.phase || "---";

        if (data.game_time != null) {
            const mins = Math.floor(data.game_time / 60);
            const secs = Math.floor(data.game_time % 60);
            gameTime.textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
        }

        if (data.current_gold != null) {
            goldEl.textContent = data.current_gold + "g";
        }

        // Level display
        if (data.level != null) {
            phaseEl.textContent = `Lv ${data.level}`;
        }

        // Scan window indicator
        if (data.scan_window_open) {
            ocrStatusBadge.textContent = "SCANNING";
            ocrStatusBadge.className = "ocr-status-badge ocr-scanning";
            ocrStatusBadge.title = "Augment pick detected — scanning screen";
        } else if (ocrAvailable) {
            ocrStatusBadge.textContent = "OCR";
            ocrStatusBadge.className = "ocr-status-badge ocr-ready";
            ocrStatusBadge.title = "OCR ready — waiting for augment pick level";
        }

        // Augment progress
        if (data.augment_state) {
            updateAugmentProgress(data.augment_state);
        }
    }

    function updateAugmentProgress(state) {
        if (!state) return;
        augmentProgress.textContent = `${state.chosen}/4`;
        augmentProgress.classList.remove("hidden");
        augmentProgress.className = "augment-progress" +
            (state.chosen >= 4 ? " complete" : "");
    }

    function showAutoChosenToast(msg) {
        augmentToast.classList.remove("hidden");
        const confPct = Math.round(msg.confidence * 100);
        augmentToast.innerHTML = `
            <div class="toast-inner">
                <span class="toast-icon">&#10003;</span>
                <span class="toast-text">Auto-detected: <strong>${esc(msg.augment_name)}</strong> (${confPct}%)</span>
            </div>
        `;
        $("section-augments").classList.remove("collapsed");

        clearTimeout(toastTimeout);
        toastTimeout = setTimeout(() => {
            augmentToast.classList.add("hidden");
        }, 4000);
    }

    function showConfirmPanel(msg) {
        augmentConfirm.classList.remove("hidden");
        augmentConfirm.innerHTML = "";
        $("section-augments").classList.remove("collapsed");

        const title = document.createElement("div");
        title.className = "confirm-title";
        title.textContent = "Which augment did you pick?";
        augmentConfirm.appendChild(title);

        (msg.candidates || []).forEach((c) => {
            const btn = document.createElement("button");
            const isBestGuess = c.id === msg.best_guess_id;
            btn.className = "btn-confirm-aug" + (isBestGuess ? " best-guess" : "");
            btn.innerHTML = `
                <span class="confirm-name">${esc(c.name)}</span>
                ${isBestGuess ? '<span class="confirm-hint">likely</span>' : ""}
            `;
            btn.addEventListener("click", () => {
                wsSend({ type: "choose_augment", augment_id: c.id });
                augmentConfirm.classList.add("hidden");
            });
            augmentConfirm.appendChild(btn);
        });
    }

    function renderEnemies(enemies) {
        enemyList.innerHTML = "";

        if (!enemies || enemies.length === 0) {
            enemyList.innerHTML = '<div style="color:var(--text-dim);padding:4px;">Unknown</div>';
            return;
        }

        enemies.forEach((e) => {
            const row = document.createElement("div");
            row.className = "enemy-row";
            const ccText = e.cc_sec > 0 ? `(${e.cc_sec.toFixed(1)}s CC)` : "";
            row.innerHTML = `
                <span class="enemy-name">${esc(e.name)}</span>
                <span class="enemy-cc">${ccText}</span>
            `;
            enemyList.appendChild(row);
        });
    }

    function renderRecommendations(data) {
        augmentList.innerHTML = "";

        if (!data.recommendations || data.recommendations.length === 0) {
            augmentList.innerHTML = '<div class="aug-empty" style="color:var(--text-dim);padding:8px;">No augment choices to evaluate</div>';
            rerollBadge.classList.add("hidden");
            rerollBanner.classList.add("hidden");
            return;
        }

        data.recommendations.forEach((rec, i) => {
            const card = document.createElement("div");
            card.className = "augment-card" + (i === 0 ? " top-pick" : "");

            const rankText = i === 0 ? ">>>" : `${i + 1}.`;
            const labelStr = rec.label.join(" \u00b7 ");
            const itemsStr = (rec.core_items_names || []).join(" \u2192 ");

            card.innerHTML = `
                <div class="aug-row">
                    <span class="aug-rank">${rankText}</span>
                    <span class="aug-name">${esc(rec.augment_name)}</span>
                    <span class="aug-score">${rec.score.toFixed(3)}</span>
                </div>
                <div class="aug-details">
                    <span class="aug-label">${esc(labelStr)}</span>
                    <span class="aug-items">${esc(itemsStr)}</span>
                </div>
                <div class="aug-explain">${esc(rec.explanation)}</div>
                <button class="btn-choose" data-augment-id="${esc(rec.augment_id)}">Choose this</button>
            `;

            card.querySelector(".btn-choose").addEventListener("click", () => {
                wsSend({ type: "choose_augment", augment_id: rec.augment_id });
            });

            augmentList.appendChild(card);
        });

        // Reroll
        if (data.suggest_reroll) {
            rerollBadge.classList.remove("hidden");
            rerollBanner.classList.remove("hidden");
            rerollReason.textContent = data.reroll_reason || "Weak choices — consider rerolling";
        } else {
            rerollBadge.classList.add("hidden");
            rerollBanner.classList.add("hidden");
        }
    }

    function renderBuild(bs) {
        if (!bs || !bs.full_build || bs.full_build.length === 0) {
            buildList.innerHTML = '<div style="color:var(--text-dim);padding:8px;">No build data</div>';
            buildFooter.textContent = "";
            return;
        }

        buildList.innerHTML = "";
        const purchased = new Set(bs.purchased_items || []);

        bs.full_build.forEach((itemId, i) => {
            const name = (bs.full_build_names && bs.full_build_names[i])
                || staticNames.items[itemId] || itemId;

            let status = "";
            let cls = "planned";
            if (purchased.has(itemId)) {
                status = "Owned";
                cls = "owned";
            } else if (itemId === bs.next_item_id) {
                status = "BUY NEXT";
                cls = "buy-next";
            } else {
                status = "Planned";
            }

            const row = document.createElement("div");
            row.className = `build-row ${cls}`;
            row.innerHTML = `
                <span class="build-slot">${i + 1}</span>
                <span class="build-name">${esc(name)}</span>
                <span class="build-status">${status}</span>
            `;
            buildList.appendChild(row);
        });

        // Footer
        if (bs.next_item_id && bs.next_item_name) {
            const goldHint = bs.gold_to_next > 0 ? ` (${bs.gold_to_next}g)` : "";
            buildFooter.textContent = `Next: ${bs.next_item_name}${goldHint}`;
            buildFooter.className = "build-footer";
        } else if (bs.gold_to_next != null && bs.gold_to_next > 0) {
            buildFooter.textContent = `Need ${bs.gold_to_next}g for next item`;
            buildFooter.className = "build-footer gold-needed";
        } else {
            buildFooter.textContent = "";
        }
    }

    // -- OCR --

    function bindOcrControls() {
        btnScan.addEventListener("click", () => {
            if (scanning) return;
            scanning = true;
            btnScan.textContent = "Scanning...";
            btnScan.disabled = true;
            wsSend({ type: "scan_augments" });
        });

        ocrAutoCheckbox.addEventListener("change", () => {
            wsSend({ type: "toggle_ocr", enabled: ocrAutoCheckbox.checked });
        });
    }

    function renderOcrResult(detected, augmentChoices) {
        if (!detected || detected.length === 0) {
            ocrDetected.classList.add("hidden");
            ocrDetected.innerHTML = "";
            return;
        }

        ocrDetected.classList.remove("hidden");
        ocrDetected.innerHTML = "";

        const title = document.createElement("div");
        title.className = "ocr-title";
        title.textContent = "Detected augments:";
        ocrDetected.appendChild(title);

        detected.forEach((d) => {
            const row = document.createElement("div");
            row.className = "ocr-detected-item";
            const confClass = d.confidence >= 80 ? "high" : d.confidence >= 65 ? "med" : "low";
            row.innerHTML = `
                <span class="ocr-name">${esc(d.name)}</span>
                <span class="ocr-conf ${confClass}">${d.confidence}%</span>
            `;
            ocrDetected.appendChild(row);
        });
    }

    // -- Section toggling --

    function bindSectionToggles() {
        document.querySelectorAll(".section-header[data-toggle]").forEach((header) => {
            header.addEventListener("click", () => {
                const section = header.closest(".section");
                section.classList.toggle("collapsed");
            });
        });
    }

    function autoExpandSections(phase) {
        const augSection = $("section-augments");
        const buildSection = $("section-build");
        const inputSection = $("section-input");
        const enemySection = $("section-enemies");

        if (phase && phase.startsWith("aug_pick")) {
            augSection.classList.remove("collapsed");
            inputSection.classList.remove("collapsed");
            buildSection.classList.add("collapsed");
        } else {
            buildSection.classList.remove("collapsed");
            enemySection.classList.remove("collapsed");
        }
    }

    // -- Augment quick-select input --

    function bindAugmentInput() {
        augmentSearch.addEventListener("input", () => {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(doAugmentSearch, 200);
        });

        tierFilter.addEventListener("change", doAugmentSearch);

        btnEvaluate.addEventListener("click", () => {
            if (selectedAugmentIds.length > 0) {
                wsSend({ type: "set_augment_choices", augment_ids: selectedAugmentIds });
                $("section-augments").classList.remove("collapsed");
            }
        });

        btnClearInput.addEventListener("click", () => {
            selectedAugmentIds = [];
            renderSelectedAugments();
            searchResults.innerHTML = "";
            augmentSearch.value = "";
            wsSend({ type: "clear_augments" });
        });
    }

    async function doAugmentSearch() {
        const query = augmentSearch.value.trim();
        const tier = tierFilter.value;

        if (query.length < 2 && !tier) {
            searchResults.innerHTML = "";
            return;
        }

        let url = `/api/augments/search?q=${encodeURIComponent(query)}`;
        if (tier) url += `&tier=${tier}`;

        try {
            const res = await fetch(url);
            const results = await res.json();
            renderSearchResults(results);
        } catch (e) {
            searchResults.innerHTML = '<div style="color:var(--red);padding:4px;">Search failed</div>';
        }
    }

    function renderSearchResults(results) {
        searchResults.innerHTML = "";

        if (results.length === 0) {
            searchResults.innerHTML = '<div style="color:var(--text-dim);padding:4px;">No matches</div>';
            return;
        }

        results.forEach((aug) => {
            if (selectedAugmentIds.includes(aug.id)) return;

            const tierLabels = { 1: "Silver", 2: "Gold", 3: "Prismatic" };
            const item = document.createElement("div");
            item.className = "search-result-item";
            item.innerHTML = `
                <span class="sr-name">${esc(aug.name)}</span>
                <span class="sr-tier tier-${aug.tier}">${tierLabels[aug.tier] || ""}</span>
            `;
            item.addEventListener("click", () => {
                if (selectedAugmentIds.length < 3 && !selectedAugmentIds.includes(aug.id)) {
                    selectedAugmentIds.push(aug.id);
                    renderSelectedAugments();
                    renderSearchResults(results);
                }
            });
            searchResults.appendChild(item);
        });
    }

    function renderSelectedAugments() {
        selectedAugments.innerHTML = "";

        selectedAugmentIds.forEach((id) => {
            const name = (staticNames.augments[id] && staticNames.augments[id].name) || id;
            const chip = document.createElement("div");
            chip.className = "selected-aug-chip";
            chip.innerHTML = `
                <span>${esc(name)}</span>
                <span class="chip-remove" data-id="${esc(id)}">&times;</span>
            `;
            chip.querySelector(".chip-remove").addEventListener("click", () => {
                selectedAugmentIds = selectedAugmentIds.filter((a) => a !== id);
                renderSelectedAugments();
            });
            selectedAugments.appendChild(chip);
        });

        btnEvaluate.disabled = selectedAugmentIds.length === 0;
        btnEvaluate.textContent = `Evaluate (${selectedAugmentIds.length}/3)`;
    }

    // -- Keyboard --

    function bindKeyboard() {
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                document.querySelectorAll(".section").forEach((s) => s.classList.add("collapsed"));
            }
        });
    }

    // -- Utilities --

    function esc(str) {
        const div = document.createElement("div");
        div.textContent = str || "";
        return div.innerHTML;
    }

    // -- Overlay mode --

    function applyOverlayMode() {
        const params = new URLSearchParams(window.location.search);
        if (params.get("mode") !== "overlay") return;

        document.body.classList.add("overlay-mode");
        // In overlay mode, hide less critical sections by default
        $("section-input").classList.add("hidden");
    }

    // -- Boot --
    applyOverlayMode();
    init();
})();
