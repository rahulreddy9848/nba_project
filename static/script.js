// static/script.js
// Robust frontend controller for GameTrack dashboard

const API = ""; // relative base

function showView(viewId) {
    document.querySelectorAll(".page-view").forEach(v => v.classList.add("hidden"));
    const view = document.getElementById(viewId);
    if (view) view.classList.remove("hidden");
    document.querySelectorAll("#nav-right .nav-link").forEach(a => {
        a.classList.remove("active");
        const target = a.getAttribute("data-view");
        if (target === viewId) a.classList.add("active");
    });
    if (viewId === "home-view") {
        loadScoreboard();
        loadStandings();
        loadLeadersCard();
    }
    if (viewId === "leaders-view") {
        loadLeadersPage();
    }
}

/* Scoreboard */
async function loadScoreboard() {
    const container = document.getElementById("scoreboard-container");
    if (!container) return;
    container.innerHTML = `<p class="loading">Loading scoreboard...</p>`;
    try {
        const res = await fetch(`${API}/api/games/scoreboard`);
        if (!res.ok) throw new Error("Scoreboard fetch failed");
        const data = await res.json();
        const games = data.games || [];
        if (!games.length) {
            container.innerHTML = `<p>No games today.</p>`;
            return;
        }
        let html = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;">`;
        games.forEach(g => {
            html += `
            <div class="score-card" onclick="window.location.href='/game/${g.gameId}'">
                <div style="display:flex;align-items:center;justify-content:space-between;">
                    <div style="display:flex;gap:12px;align-items:center">
                        <img src="${g.homeLogo}" style="width:48px;height:48px;object-fit:contain" onerror="this.src='/static/logo.png'"/>
                        <div>
                            <div style="font-weight:600">${g.homeAbbr || g.homeTeam}</div>
                            <div class="game-status">${g.gameStatus || ''}</div>
                        </div>
                    </div>
                    <div style="text-align:center">
                        <div style="font-weight:700;font-size:1.25rem">${g.homeScore ?? 0}</div>
                        <div style="color:#999;font-size:0.85rem">vs</div>
                        <div style="font-weight:700;font-size:1.25rem">${g.awayScore ?? 0}</div>
                    </div>
                    <div style="display:flex;gap:12px;align-items:center">
                        <div style="text-align:right">
                            <div style="font-weight:600">${g.awayAbbr || g.awayTeam}</div>
                            <div class="game-status">${new Date(g.startTimeUTC || "").toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) || ''}</div>
                        </div>
                        <img src="${g.awayLogo}" style="width:48px;height:48px;object-fit:contain" onerror="this.src='/static/logo.png'"/>
                    </div>
                </div>
            </div>`;
        });
        html += `</div>`;
        container.innerHTML = html;
    } catch (err) {
        console.error("loadScoreboard:", err);
        container.innerHTML = `<p class="error">Failed to load scoreboard.</p>`;
    }
}

/* Standings */
async function loadStandings() {
    const eastBox = document.getElementById("east-standings");
    const westBox = document.getElementById("west-standings");
    if (!eastBox || !westBox) return;
    eastBox.innerHTML = `<h3>Eastern Conference</h3><p class="loading">Loading...</p>`;
    westBox.innerHTML = `<h3>Western Conference</h3><p class="loading">Loading...</p>`;
    try {
        const res = await fetch(`${API}/api/standings`);
        if (!res.ok) throw new Error("standings fetch failed");
        const data = await res.json();
        const east = data.east || [];
        const west = data.west || [];
        function tableFromRows(rows) {
            if (!rows.length) return `<p>No standings available.</p>`;
            let html = `<table><thead><tr><th>Rank</th><th>Team</th><th>W</th><th>L</th><th>GB</th></tr></thead><tbody>`;
            rows.forEach((r, i) => {
                const team = r.TeamName || r.TEAM || r.teamName || r.TEAM_NAME || r.abbreviation || (r.TeamTricode || r.TeamAbbr) || "-";
                const wins = r.WINS ?? r.WIN ?? r.wins ?? "-";
                const losses = r.LOSSES ?? r.LOSS ?? r.losses ?? "-";
                const gb = r.GamesBack ?? r.gb ?? r.GB ?? "-";
                html += `<tr><td>${i+1}</td><td>${team}</td><td>${wins}</td><td>${losses}</td><td>${gb}</td></tr>`;
            });
            html += `</tbody></table>`;
            return html;
        }
        eastBox.innerHTML = `<h3>Eastern Conference</h3>` + tableFromRows(east);
        westBox.innerHTML = `<h3>Western Conference</h3>` + tableFromRows(west);
    } catch (err) {
        console.error("loadStandings:", err);
        eastBox.innerHTML = `<p class="error">Failed to load standings.</p>`;
        westBox.innerHTML = `<p class="error">Failed to load standings.</p>`;
    }
}

/* Leaders (home card & full view) */
async function loadLeadersCard() {
    const container = document.getElementById("leaders-card");
    if (!container) return;
    container.innerHTML = `<h2>League Leaders</h2><p class="loading">Loading...</p>`;
    try {
        const res = await fetch(`${API}/api/leaders/homepage`);
        if (!res.ok) throw new Error("leaders/homepage fetch failed");
        const data = await res.json();
        let html = `<h2>League Leaders</h2>`;
        ["PTS","REB","AST"].forEach(stat => {
            const list = data[stat] || [];
            html += `<div style="margin-top:8px;"><strong>${stat}</strong><ol style="margin:4px 0 8px 18px;">`;
            list.slice(0,5).forEach(p => {
                const name = p.PLAYER || p.PLAYER_NAME || p.player;
                const team = p.TEAM || p.abbreviation || "";
                const val = p[stat] ?? p[stat.toLowerCase()] ?? "";
                html += `<li>${name} (${team}) — ${val}</li>`;
            });
            html += `</ol></div>`;
        });
        container.innerHTML = html;
    } catch (err) {
        console.error("loadLeadersCard:", err);
        container.innerHTML = `<h2>League Leaders</h2><p class="error">Failed to load leaders.</p>`;
    }
}

async function loadLeadersPage() {
    const statSelect = document.getElementById("stat-select");
    const container = document.getElementById("leaders-table-container");
    if (!container || !statSelect) return;
    const stat = (statSelect.value || "PTS").toUpperCase();
    container.innerHTML = `<p class="loading">Loading leaders for ${stat}...</p>`;
    try {
        const res = await fetch(`${API}/api/leaders/${stat}`);
        if (!res.ok) {
            const j = await res.json().catch(()=>({}));
            throw new Error(j.error || "leaders fetch failed");
        }
        let data = await res.json();
        if (!data) {
            container.innerHTML = `<p>No leaders found for ${stat}.</p>`;
            return;
        }
        if (!Array.isArray(data) && data.data) data = data.data;
        let html = `<table><thead><tr><th>Rank</th><th>Player</th><th>Team</th><th>${stat}</th></tr></thead><tbody>`;
        data.forEach((p, i) => {
            const name = p.PLAYER || p.PLAYER_NAME || p.PLAYER_DISPLAY || p.player || p.PLAYER_DISPLAY_NAME || "-";
            const team = p.TEAM || p.abbreviation || p.TEAM_ABBREVIATION || p.team || "";
            const val = p[stat] ?? p[stat.toLowerCase()] ?? p.value ?? "-";
            const id = p.PERSON_ID || p.PLAYER_ID || p.PID || p.id || '';
            html += `<tr class="clickable-row" onclick="window.location.href='/player/${id}'"><td>${i+1}</td><td>${name}</td><td>${team}</td><td>${val}</td></tr>`;
        });
        html += `</tbody></table>`;
        container.innerHTML = html;
    } catch (err) {
        console.error("loadLeadersPage:", err);
        container.innerHTML = `<p class="error">Failed to load leaders: ${err.message}</p>`;
    }
}

/* Teams grid */
async function loadTeamsGrid() {
    const grid = document.getElementById("teams-grid");
    if (!grid) return;
    grid.innerHTML = `<p class="loading">Loading teams...</p>`;
    try {
        const res = await fetch(`${API}/api/teams`);
        if (!res.ok) throw new Error("teams fetch failed");
        const teams = await res.json();
        if (!teams.length) {
            grid.innerHTML = `<p>No teams found.</p>`;
            return;
        }
        grid.innerHTML = "";
        teams.forEach(team => {
            const card = document.createElement("div");
            card.className = "team-card";
            card.onclick = () => window.location.href = `/team/${team.id || team.teamId || team.TEAM_ID}`;
            card.innerHTML = `
                <img src="${team.logoUrl || team.logo || '/static/logo.png'}" onerror="this.src='/static/logo.png'"/>
                <h3>${team.full_name || team.fullName || team.nickname || team.teamName}</h3>
                <p style="color:#aaa;margin:0;">${team.abbreviation || team.tricode || ''}</p>
            `;
            grid.appendChild(card);
        });
    } catch (err) {
        console.error("loadTeamsGrid:", err);
        if (grid) grid.innerHTML = `<p class="error">Failed to load teams.</p>`;
    }
}

/* On DOM ready */
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("#nav-title").forEach(e => e.textContent = "GameTrack");
    document.querySelectorAll("#nav-logo").forEach(img => {
        if (img) {
            img.onerror = () => { img.src = '/static/logo.png'; };
            if (!img.src.includes('/static/logo.png')) {
                img.src = '/static/logo.png';
            }
        }
    });
    document.querySelectorAll("#nav-right .nav-link").forEach(a => {
        const view = a.getAttribute("data-view");
        if (view) {
            a.addEventListener("click", (e) => {
                e.preventDefault();
                showView(view);
            });
        }
    });

    if (document.getElementById("home-view")) {
        showView('home-view');
    }
    if (document.getElementById("teams-grid")) {
        loadTeamsGrid();
    }
    if (document.getElementById("leaders-table-container")) {
        loadLeadersCard();
    }
});
