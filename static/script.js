// static/script.js
// Robust frontend controller for GameTrack dashboard

const API = ""; // relative base
let teamLogoMap = {}; // --- NEW: Cache for team logos ---

function showView(viewId) {
    document.querySelectorAll(".page-view").forEach(v => v.classList.add("hidden"));
    const view = document.getElementById(viewId);
    if (view) view.classList.remove("hidden");
    
    document.querySelectorAll("#nav-right .nav-link").forEach(a => {
        a.classList.remove("active");
        const target = a.getAttribute("data-view");
        if (target === viewId) {
            a.classList.add("active");
        } else if (viewId === 'home-view' && a.getAttribute('href') === '/') {
             a.classList.add("active");
        }
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

/* --- NEW: Function to load team logos once --- */
async function loadTeamLogoMap() {
    // Only fetch if the map is empty
    if (Object.keys(teamLogoMap).length > 0) return;
    
    try {
        const res = await fetch(`${API}/api/teams`);
        if (!res.ok) throw new Error("Team fetch failed");
        const teams = await res.json();
        teams.forEach(team => {
            const teamId = team.id || team.teamId || team.TEAM_ID;
            teamLogoMap[teamId] = team.logoUrl || '/static/logo.png';
        });
    } catch (err) {
        console.error("loadTeamLogoMap:", err);
    }
}

/* Scoreboard */
async function loadScoreboard() {
    const container = document.getElementById("scoreboard-container");
    if (!container) return;
    
    // Keep the h2, only replace the content below it
    container.innerHTML = `<h2>Today's Games</h2><p class="loading">Loading scoreboard...</p>`;
    
    try {
        const res = await fetch(`${API}/api/games/scoreboard`);
        if (!res.ok) throw new Error("Scoreboard fetch failed");
        const data = await res.json();
        const games = data.games || [];
        
        if (!games.length) {
            container.innerHTML = `<h2>Today's Games</h2><p>No games scheduled for today.</p>`;
            return;
        }

        // --- NEW: Split games into Final and Upcoming ---
        const finalGames = games.filter(g =>
            g.gameStatus && (g.gameStatus.toLowerCase().includes('final') || g.gameStatus.toLowerCase().includes('completed'))
        );
        const upcomingGames = games.filter(g =>
            !g.gameStatus || (!g.gameStatus.toLowerCase().includes('final') && !g.gameStatus.toLowerCase().includes('completed'))
        );
        
        // Helper function to build a single game card
        const buildGameCard = (g) => {
            const isFinal = g.gameStatus && g.gameStatus.toLowerCase().includes('final');
            const gameTime = new Date(g.startTimeUTC || "1970-01-01T00:00:00Z").toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            // Use game status if it's live, otherwise show the time
            const statusText = isFinal ? "Final" : (g.gameStatus.includes('Qtr') || g.gameStatus.includes('Half') || g.gameStatus.includes('PM') || g.gameStatus.includes('AM') ? g.gameStatus : gameTime);

            return `
            <div class="score-card" onclick="window.location.href='/game/${g.gameId}'" title="Click for Box Score">
                <div class="score-team">
                    <img src="${g.awayLogo}" onerror="this.src='https://placehold.co/40x40/333/FFF?text=NBA'"/>
                    <span>${g.awayAbbr || g.awayTeam}</span>
                    <strong class="score">${g.awayScore ?? 0}</strong>
                </div>
                <div class="score-team">
                    <img src="${g.homeLogo}" onerror="this.src='https://placehold.co/40x40/333/FFF?text=NBA'"/>
                    <span>${g.homeAbbr || g.homeTeam}</span>
                    <strong class="score">${g.homeScore ?? 0}</strong>
                </div>
                <div class="game-status">${statusText}</div>
            </div>`;
        };
        
        let html = `<h2>Today's Games</h2>`;
        
        // Grid for all games
        html += `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:15px;">`;

        // Show upcoming games first, then final
        upcomingGames.forEach(g => {
            html += buildGameCard(g);
        });
        
        finalGames.forEach(g => {
            html += buildGameCard(g);
        });

        html += `</div>`;
        container.innerHTML = html;

    } catch (err) {
        console.error("loadScoreboard:", err);
        container.innerHTML = `<h2>Today's Games</h2><p class="error">Failed to load scoreboard.</p>`;
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
        // --- FIX: Load logos before loading standings ---
        await loadTeamLogoMap();

        const res = await fetch(`${API}/api/standings`);
        if (!res.ok) throw new Error("standings fetch failed");
        const data = await res.json();
        const east = data.east || [];
        const west = data.west || [];

        function tableFromRows(rows) {
            if (!rows.length) return `<p>No standings available.</p>`;
            // --- FIX: Added table-container div ---
            let html = `<div class="table-container"><table><thead><tr><th>Rank</th><th>Team</th><th>W</th><th>L</th><th>GB</th></tr></thead><tbody>`;
            rows.forEach((r, i) => {
                const team = r.TeamName || r.TEAM || r.teamName || r.TEAM_NAME || r.abbreviation || (r.TeamTricode || r.TeamAbbr) || "-";
                
                // --- FIX: Get TeamID and Logo URL ---
                const teamId = r.TeamID || r.teamId || r.teamID || 0;
                const logoUrl = teamLogoMap[teamId] || '/static/logo.png';

                const wins = r.WINS ?? r.WIN ?? r.wins ?? "-";
                const losses = r.LOSSES ?? r.LOSS ?? r.losses ?? "-";
                const gb = r.GamesBack ?? r.gb ?? r.GB ?? "-";
                
                // --- FIX: Add logo to team cell ---
                html += `<tr>
                            <td>${i+1}</td>
                            <td><img src="${logoUrl}" class="standings-logo" onerror="this.src='/static/logo.png'"/> ${team}</td>
                            <td>${wins}</td>
                            <td>${losses}</td>
                            <td>${gb}</td>
                         </tr>`;
            });
            html += `</tbody></table>`;
            // --- FIX: Added closing div ---
            html += `</div>`;
            return html;
        }
        eastBox.innerHTML = `<h3>Eastern Conference</h3>` + tableFromRows(east);
        westBox.innerHTML = `<h3>Western Conference</h3>` + tableFromRows(west);
    } catch (err) {
        console.error("loadStandings:", err);
        eastBox.innerHTML = `<h3>Eastern Conference</h3><p class="error">Failed to load standings.</p>`;
        westBox.innerHTML = `<h3>Western Conference</h3><p class="error">Failed to load standings.</p>`;
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
        html += `<div style="display:flex; flex-direction:column; gap: 15px;">`;

        ["PTS","REB","AST"].forEach(stat => {
            const list = data[stat] || [];
            html += `<div style="margin-top:8px;"><strong>${stat} LEADERS</strong><div class="table-container"><table style="margin-top: 8px;"><tbody>`;
            list.slice(0, 3).forEach((p, i) => { // Top 3 for the card
                const name = p.PLAYER || p.PLAYER_NAME || p.player;
                const team = p.TEAM || p.abbreviation || "";
                const val = p[stat] ?? p[stat.toLowerCase()] ?? "";
                
                // --- FIX: Use PERSON_ID for the link ---
                const id = p.PERSON_ID || p.PLAYER_ID || p.PID || p.id || '';
                
                const clickHandler = id ? `onclick="window.location.href='/player/${id}'"` : "";
                const rowClass = id ? "clickable-row" : "";
                const title = id ? "View Player Page" : "";

                html += `<tr class="${rowClass}" ${clickHandler} title="${title}">
                            <td><strong>${i+1}.</strong></td>
                            <td>${name} (${team})</td>
                            <td style="text-align:right; font-weight: 600;">${val}</td>
                         </tr>`;
            });
            html += `</tbody></table></div></div>`;
        });
        html += `</div>`;
        // Add a "View All Leaders" button
        html += `<button class="back-button" onclick="showView('leaders-view')" style="margin-top: 20px; width: 100%;">View All Leaderboards</button>`;
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

        // --- FIX: Update table header for more stats ---
        // --- FIX: Added table-container div ---
        let html = `<div class="table-container"><table><thead><tr><th>Rank</th><th>Player</th><th>Team</th><th>PTS</th><th>REB</th><th>AST</th></tr></thead><tbody>`;
        
        data.forEach((p, i) => {
            const name = p.PLAYER || p.PLAYER_NAME || p.PLAYER_DISPLAY || p.player || p.PLAYER_DISPLAY_NAME || "-";
            const team = p.TEAM || p.abbreviation || p.TEAM_ABBREVIATION || p.team || "";
            
            // --- FIX: Get all primary stats ---
            const pts = p.PTS ?? p.pts ?? 0;
            const reb = p.REB ?? p.reb ?? 0;
            const ast = p.AST ?? p.ast ?? 0;
            
            const id = p.PERSON_ID || p.PLAYER_ID || p.PID || p.id || '';
            
            // --- FIX: Populate all stats in the row ---
            html += `<tr class="clickable-row" onclick="window.location.href='/player/${id}'">
                        <td>${i+1}</td>
                        <td>${name}</td>
                        <td>${team}</td>
                        <td>${pts}</td>
                        <td>${reb}</td>
                        <td>${ast}</td>
                     </tr>`;
        });
        html += `</tbody></table>`;
        // --- FIX: Added closing div, setting innerHTML, and catch block ---
        html += `</div>`;
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
        grid.innerHTML = ""; // Clear loading
        teams.forEach(team => {
            const card = document.createElement("div");
            card.className = "team-card"; // Use new class from styles.css
            card.onclick = () => window.location.href = `/team/${team.id || team.teamId || team.TEAM_ID}`;
            card.innerHTML = `
                <img src="${team.logoUrl || team.logo || 'https://placehold.co/85x85/333/FFF?text=NBA'}" onerror="this.src='https://placehold.co/85x85/333/FFF?text=NBA'"/>
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
    // Update logo placeholder
    document.querySelectorAll("#nav-logo").forEach(img => {
        if (img) {
            img.onerror = () => { img.src = 'https://placehold.co/40x40/007bff/FFF?text=GT'; };
        }
    });

    // Setup nav link SPA behavior
    document.querySelectorAll("#nav-right .nav-link").forEach(a => {
        const view = a.getAttribute("data-view");
        if (view) {
            a.addEventListener("click", (e) => {
                e.preventDefault();
                // Check if it's a link to a different page or a view
                if (a.getAttribute('href') && a.getAttribute('href') !== '#') {
                    window.location.href = a.getAttribute('href');
                } else {
                    showView(view);
                }
            });
        }
    });

    // Initial page load logic
    if (document.getElementById("home-view")) {
        showView('home-view');
    }
    if (document.getElementById("teams-grid")) {
        loadTeamsGrid(); // This will now use the new card style
    }
    // Note: other page-specific init scripts are in their own html files
    // (team.html, player.html, etc.)
});