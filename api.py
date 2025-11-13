#!/usr/bin/env python3
"""
api.py - GameTrack backend

Run:
    python api.py

This file provides the Flask app and all API endpoints used by the frontend:
 - /api/teams
 - /api/standings
 - /api/games/scoreboard
 - /api/leaders/homepage
 - /api/leaders/<stat_category>
 - /api/team/<team_id>/roster
 - /api/team/<team_id>/schedule
 - /api/player/<player_id>/profile
 - /api/player/<player_id>/gamelog
 - /api/game/<game_id>/boxscore

Notes:
 - If nba_api calls fail, endpoints return safe sample data so UI remains functional.
"""
import os
import time
import json
import logging
from datetime import datetime
from flask import Flask, jsonify, render_template, send_from_directory
from flask_cors import CORS
import pandas as pd

# Try importing nba_api modules; if not available, endpoints will fall back.
try:
    from nba_api.stats.static import teams as teams_static
    from nba_api.stats.endpoints import (
        scoreboardv2,
        leaguestandingsv3,
        leaguedashplayerstats,
        commonteamroster,
        commonplayerinfo,
        playergamelog,
        boxscoretraditionalv3,
        boxscoreadvancedv3
    )
    NBA_API_AVAILABLE = True
except Exception:
    NBA_API_AVAILABLE = False

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)
app.config['JSON_SORT_KEYS'] = False
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# Config
CURRENT_SEASON = "2025-26"
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ACCOLADES_FILE = os.path.join(STATIC_DIR, "accolades_active.json")

# Simple in-memory cache
_CACHE = {}
def cache_get(key):
    v = _CACHE.get(key)
    if not v:
        return None
    expiry, val = v
    if time.time() > expiry:
        del _CACHE[key]
        return None
    return val

def cache_set(key, val, ttl=30):
    _CACHE[key] = (time.time() + ttl, val)

# Helpers
def safe_records_from_df(df):
    if df is None:
        return []
    if isinstance(df, list):
        return df
    if len(df) == 0:
        return []
    df = df.copy()
    df = df.replace([pd.NA, pd.NaT, float('inf'), float('-inf')], pd.NA)
    df = df.fillna(0)
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].apply(lambda v: v.isoformat() if not pd.isna(v) else None)
    df = df.loc[:, ~df.columns.duplicated()]
    return df.to_dict(orient='records')

def load_accolades():
    if os.path.exists(ACCOLADES_FILE):
        try:
            with open(ACCOLADES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            app.logger.warning("Failed to load accolades file.")
            return {}
    return {}

# Routes: templates
@app.route('/')
def index(): return render_template('index.html')
@app.route('/teams')
def teams_page(): return render_template('teams.html')
@app.route('/team/<int:team_id>')
def team_page(team_id): return render_template('team.html', team_id=team_id)
@app.route('/player/<int:player_id>')
def player_page(player_id): return render_template('player.html', player_id=player_id)
@app.route('/game/<game_id>')
def game_page(game_id): return render_template('game.html', game_id=game_id)
@app.route('/charts')
def charts_page(): return render_template('charts.html')

# Serve file if logo requested explicitly (helps local dev)
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# ---------------------------
# API: /api/teams
# ---------------------------
@app.route('/api/teams')
def api_teams():
    cached = cache_get('teams')
    if cached:
        return jsonify(cached)
    try:
        if NBA_API_AVAILABLE:
            all_teams = teams_static.get_teams()
        else:
            all_teams = []
        # ensure each team has id and logoUrl
        for t in all_teams:
            tid = t.get('id') or t.get('teamId') or t.get('TEAM_ID')
            if tid:
                t['logoUrl'] = f"https://cdn.nba.com/logos/nba/{tid}/global/L/logo.svg"
            else:
                t['logoUrl'] = "/static/logo.png"
        if not all_teams:
            # fallback sample teams
            all_teams = [
                {"id":1610612747,"full_name":"Los Angeles Lakers","abbreviation":"LAL","logoUrl":"/static/logo.png"},
                {"id":1610612744,"full_name":"Golden State Warriors","abbreviation":"GSW","logoUrl":"/static/logo.png"}
            ]
        cache_set('teams', all_teams, ttl=3600)
        return jsonify(all_teams)
    except Exception as e:
        app.logger.exception("api_teams failed")
        sample = [
            {"id":1610612747,"full_name":"Los Angeles Lakers","abbreviation":"LAL","logoUrl":"/static/logo.png"},
            {"id":1610612744,"full_name":"Golden State Warriors","abbreviation":"GSW","logoUrl":"/static/logo.png"}
        ]
        cache_set('teams', sample, ttl=3600)
        return jsonify(sample)

# ---------------------------
# API: /api/standings
# ---------------------------
@app.route('/api/standings')
def api_standings():
    cached = cache_get('standings')
    if cached:
        return jsonify(cached)
    try:
        if NBA_API_AVAILABLE:
            s = leaguestandingsv3.LeagueStandingsV3(season=CURRENT_SEASON)
            df = s.get_data_frames()[0]
            # normalize column names
            df = df.rename(columns={c: c if isinstance(c,str) else str(c) for c in df.columns})
            colmap = {}
            for c in df.columns:
                lc = c.lower()
                if 'team' in lc and 'id' in lc: colmap[c] = 'TeamID'
                if 'team' in lc and ('tricode' in lc or 'tri' in lc or 'abbr' in lc): colmap[c] = 'TeamTricode'
                if 'team' in lc and ('name' in lc): colmap[c] = 'TeamName'
                if lc == 'conference': colmap[c] = 'Conference'
                if 'win' == lc or lc == 'wins': colmap[c] = 'WINS'
                if 'loss' == lc or lc == 'losses': colmap[c] = 'LOSSES'
                if 'conferencerank' in lc or 'conference_rank' in lc: colmap[c] = 'ConferenceRank'
                if 'gamesback' in lc or 'gb' == lc: colmap[c] = 'GamesBack'
            if colmap:
                df = df.rename(columns=colmap)
            if 'Conference' in df.columns:
                east = df[df['Conference'].astype(str).str.lower() == 'east']
                west = df[df['Conference'].astype(str).str.lower() == 'west']
            else:
                east = df[df.apply(lambda r: 'east' in str(r.values).lower(), axis=1)]
                west = df[df.apply(lambda r: 'west' in str(r.values).lower(), axis=1)]
            out = {"east": safe_records_from_df(east), "west": safe_records_from_df(west)}
            cache_set('standings', out, ttl=30)
            return jsonify(out)
        else:
            raise RuntimeError("nba_api not available")
    except Exception as e:
        app.logger.exception("api_standings failed; returning sample")
        sample = {
            "east": [
                {"TeamName":"Boston Celtics","WINS":50,"LOSSES":22,"GamesBack":0},
                {"TeamName":"Milwaukee Bucks","WINS":45,"LOSSES":27,"GamesBack":5}
            ],
            "west": [
                {"TeamName":"Phoenix Suns","WINS":48,"LOSSES":24,"GamesBack":0},
                {"TeamName":"Denver Nuggets","WINS":44,"LOSSES":28,"GamesBack":4}
            ]
        }
        cache_set('standings', sample, ttl=30)
        return jsonify(sample)

# ---------------------------
# API: /api/games/scoreboard
# ---------------------------
@app.route('/api/games/scoreboard')
def api_scoreboard():
    cached = cache_get('scoreboard')
    if cached:
        return jsonify(cached)
    try:
        if not NBA_API_AVAILABLE:
            raise RuntimeError("nba_api not available")
        # Use today's date (Eastern)
        from pytz import timezone
        ET = timezone('US/Eastern')
        now_et = datetime.now(ET)
        date_str = now_et.strftime('%Y-%m-%d')
        sb = scoreboardv2.ScoreboardV2(game_date=date_str)
        dfs = sb.get_data_frames()
        games_df = None
        linescore_df = None
        for df in dfs:
            cols = [c.lower() for c in df.columns]
            if 'game_id' in cols or 'gameid' in cols:
                games_df = df
            if 'team_id' in cols and ('pts' in cols or 'points' in cols):
                linescore_df = df
        games = safe_records_from_df(games_df)
        scores = safe_records_from_df(linescore_df)
        teams_cache = cache_get('teams') or teams_static.get_teams() if NBA_API_AVAILABLE else []
        teams_map = {t.get('id') or t.get('teamId') or t.get('TEAM_ID'): t for t in teams_cache}
        unified = []
        for g in games:
            gid = g.get('GAME_ID') or g.get('gameId') or g.get('GAMEID')
            home_id = g.get('HOME_TEAM_ID') or g.get('homeTeamId') or g.get('HOME_TEAM_ID')
            away_id = g.get('VISITOR_TEAM_ID') or g.get('visitorTeamId') or g.get('VISITOR_TEAM_ID')
            home_score = None; away_score = None
            for s in scores:
                tid = s.get('TEAM_ID') or s.get('teamId') or s.get('TEAMID')
                if tid == home_id:
                    home_score = s.get('PTS') or s.get('pts') or s.get('POINTS')
                if tid == away_id:
                    away_score = s.get('PTS') or s.get('pts') or s.get('POINTS')
            home_team = teams_map.get(home_id, {})
            away_team = teams_map.get(away_id, {})
            unified.append({
                "gameId": gid,
                "gameStatus": g.get('GAME_STATUS_TEXT') or g.get('GAME_STATUS') or g.get('STATUS'),
                "homeTeamId": home_id,
                "awayTeamId": away_id,
                "homeTeam": home_team.get('full_name') or home_team.get('nickname') or g.get('HOME_TEAM_CITY') or '',
                "awayTeam": away_team.get('full_name') or away_team.get('nickname') or g.get('VISITOR_TEAM_CITY') or '',
                "homeAbbr": home_team.get('abbreviation') or g.get('HOME_TEAM_ABBREVIATION') or '',
                "awayAbbr": away_team.get('abbreviation') or g.get('VISITOR_TEAM_ABBREVIATION') or '',
                "homeLogo": f"https://cdn.nba.com/logos/nba/{home_id}/global/L/logo.svg" if home_id else "/static/logo.png",
                "awayLogo": f"https://cdn.nba.com/logos/nba/{away_id}/global/L/logo.svg" if away_id else "/static/logo.png",
                "homeScore": home_score if home_score is not None else 0,
                "awayScore": away_score if away_score is not None else 0,
                "startTimeUTC": g.get('GAME_DATE_EST') or g.get('GAME_DATE'),
                "arena": g.get('ARENA') or g.get('ARENA_NAME') or ''
            })
        out = {"games": unified}
        cache_set('scoreboard', out, ttl=15)
        return jsonify(out)
    except Exception as e:
        app.logger.exception("api_scoreboard failed; returning sample")
        sample = {
            "games": [
                {
                    "gameId": "sample-1",
                    "gameStatus": "Final",
                    "homeTeamId": 1610612747,
                    "awayTeamId": 1610612750,
                    "homeTeam": "Los Angeles Lakers",
                    "awayTeam": "Golden State Warriors",
                    "homeAbbr": "LAL",
                    "awayAbbr": "GSW",
                    "homeLogo": f"https://cdn.nba.com/logos/nba/1610612747/global/L/logo.svg",
                    "awayLogo": f"https://cdn.nba.com/logos/nba/1610612744/global/L/logo.svg",
                    "homeScore": 112,
                    "awayScore": 108,
                    "startTimeUTC": datetime.utcnow().isoformat(),
                    "arena": "Staples Center"
                }
            ]
        }
        cache_set('scoreboard', sample, ttl=15)
        return jsonify(sample)

# ---------------------------
# API: /api/leaders/homepage
# ---------------------------
@app.route('/api/leaders/homepage')
def api_leaders_home():
    cached = cache_get('leaders_home')
    if cached:
        return jsonify(cached)
    try:
        if not NBA_API_AVAILABLE:
            raise RuntimeError("nba_api not available")
        stats = leaguedashplayerstats.LeagueDashPlayerStats(per_mode_detailed='PerGame', season=CURRENT_SEASON, season_type_all_star='Regular Season', timeout=30)
        df = stats.get_data_frames()[0]
        teams_df = pd.DataFrame(teams_static.get_teams())
        out = {}
        for stat in ['PTS','REB','AST']:
            col = stat if stat in df.columns else next((c for c in df.columns if c.lower()==stat.lower()), stat)
            top5 = df.sort_values(by=col, ascending=False).head(5) if col in df.columns else df.head(5)
            merged = pd.merge(top5, teams_df, left_on='TEAM_ID', right_on='id', how='left')
            merged = merged.loc[:, ~merged.columns.duplicated()]
            out[stat] = [{"PLAYER": r.get('PLAYER_NAME') or r.get('PLAYER'), "TEAM": r.get('abbreviation'), stat: r.get(stat)} for r in merged.to_dict(orient='records')]
        cache_set('leaders_home', out, ttl=30)
        return jsonify(out)
    except Exception as e:
        app.logger.exception("api_leaders_home failed; returning sample")
        sample = {
            "PTS": [{"PLAYER":"L. James","TEAM":"LAL","PTS":30.1},{"PLAYER":"S. Curry","TEAM":"GSW","PTS":29.4}],
            "REB": [{"PLAYER":"N. Jokic","TEAM":"DEN","REB":11.2},{"PLAYER":"G. Antetokounmpo","TEAM":"MIL","REB":10.8}],
            "AST": [{"PLAYER":"L. Doncic","TEAM":"DAL","AST":9.8},{"PLAYER":"C. Paul","TEAM":"PHX","AST":8.9}]
        }
        cache_set('leaders_home', sample, ttl=30)
        return jsonify(sample)

# ---------------------------
# API: /api/leaders/<stat_category>
# ---------------------------
@app.route('/api/leaders/<stat_category>')
def api_leaders_full(stat_category):
    stat = stat_category.upper()
    allowed = ['PTS','AST','REB','BLK','STL','FGM','FGA','FG3M','FG3A','FTM','FTA','FG_PCT','FG3_PCT','FT_PCT']
    if stat not in allowed:
        return jsonify({"error":"invalid stat"}), 400
    try:
        if not NBA_API_AVAILABLE:
            raise RuntimeError("nba_api not available")
        stats = leaguedashplayerstats.LeagueDashPlayerStats(per_mode_detailed='PerGame', season=CURRENT_SEASON, season_type_all_star='Regular Season', timeout=30)
        df = stats.get_data_frames()[0]
        if stat not in df.columns:
            match = next((c for c in df.columns if c.lower()==stat.lower()), None)
            if match:
                df = df.rename(columns={match: stat})
        df_sorted = df.sort_values(by=stat, ascending=False).head(25) if stat in df.columns else df.head(25)
        teams_df = pd.DataFrame(teams_static.get_teams()) if NBA_API_AVAILABLE else pd.DataFrame()
        merged = pd.merge(df_sorted, teams_df, left_on='TEAM_ID', right_on='id', how='left') if not teams_df.empty else df_sorted
        merged = merged.loc[:, ~merged.columns.duplicated()]
        recs = safe_records_from_df(merged)
        return jsonify(recs)
    except Exception as e:
        app.logger.exception("api_leaders_full failed; returning sample")
        sample = [
            {"PLAYER":"L. James","TEAM":"LAL","PTS":30.1,"PERSON_ID":2544},
            {"PLAYER":"S. Curry","TEAM":"GSW","PTS":29.4,"PERSON_ID":201939}
        ]
        return jsonify(sample)

# ---------------------------
# API: /api/team/<team_id>/roster
# ---------------------------
@app.route('/api/team/<int:team_id>/roster')
def api_team_roster(team_id):
    try:
        if NBA_API_AVAILABLE:
            r = commonteamroster.CommonTeamRoster(team_id=team_id)
            df = r.get_data_frames()[0]
            recs = safe_records_from_df(df)
            return jsonify(recs)
        else:
            raise RuntimeError("nba_api not available")
    except Exception as e:
        app.logger.exception("api_team_roster failed; returning sample")
        sample = [
            {"PLAYER_ID":201939,"PLAYER":"Stephen Curry","NUM":"30","POSITION":"G","AGE":36,"HEIGHT":"6-2","WEIGHT":"185","SCHOOL":"Davidson"},
            {"PLAYER_ID":2544,"PLAYER":"LeBron James","NUM":"23","POSITION":"F","AGE":39,"HEIGHT":"6-9","WEIGHT":"250","SCHOOL":"St. Vincent-St. Mary"}
        ]
        return jsonify(sample)

# ---------------------------
# API: /api/team/<team_id>/schedule
# ---------------------------
@app.route('/api/team/<int:team_id>/schedule')
def api_team_schedule(team_id):
    """
    Returns upcoming and recent games for a given team.
    Uses LeagueGameFinder (compatible with your nba_api version).
    """
    from datetime import datetime

    try:
        if not NBA_API_AVAILABLE:
            raise RuntimeError("nba_api not available")

        from nba_api.stats.endpoints import leaguegamefinder

        # ✔ Correct syntax for your nba_api version:
        finder = leaguegamefinder.LeagueGameFinder(
            team_id_nullable=team_id,
            season_nullable=CURRENT_SEASON
        )

        games = finder.get_data_frames()[0]

        # Normalize date column
        date_col = "GAME_DATE" if "GAME_DATE" in games.columns else "GAME_DATE_EST"
        games[date_col] = pd.to_datetime(games[date_col])

        # Rename for consistency
        games.rename(columns={date_col: "GAME_DATE"}, inplace=True)

        # Convert GAME_ID to string
        games["GAME_ID"] = games["GAME_ID"].astype(str)

        # Sort games by date
        games = games.sort_values("GAME_DATE")

        today = pd.Timestamp(datetime.now().date())

        # Split upcoming/recent
        upcoming_df = games[games["GAME_DATE"] >= today].head(5)
        recent_df = games[games["GAME_DATE"] < today].tail(5)

        # Format output
        def format_row(row):
            return {
                "GAME_ID": row["GAME_ID"],
                "GAME_DATETIME": row["GAME_DATE"].isoformat(),
                "MATCHUP": row.get("MATCHUP", ""),
                "WL": row.get("WL")
            }

        return jsonify({
            "upcoming": [format_row(r) for _, r in upcoming_df.iterrows()],
            "recent":  [format_row(r) for _, r in recent_df.iterrows()]
        })

    except Exception as e:
        app.logger.error("api_team_schedule failed, returning sample fallback: %s", e)

        sample = {
            "upcoming": [
                {"GAME_ID": "1001", "GAME_DATETIME": "2025-04-10T19:30:00", "MATCHUP": "LAL vs GSW", "WL": None}
            ],
            "recent": [
                {"GAME_ID": "999", "GAME_DATETIME": "2025-04-08T19:30:00", "MATCHUP": "LAL @ BOS", "WL": "L"}
            ]
        }
        return jsonify(sample)


# ---------------------------
# API: /api/player/<player_id>/profile
# ---------------------------
@app.route('/api/player/<int:player_id>/profile')
def api_player_profile(player_id):
    try:
        if NBA_API_AVAILABLE:
            info = commonplayerinfo.CommonPlayerInfo(player_id=player_id).get_data_frames()
            if info and len(info) > 0:
                df_info = info[0]
                recs = safe_records_from_df(df_info)
                return jsonify({"info": recs})
        raise RuntimeError("nba_api not available or no data")
    except Exception as e:
        app.logger.exception("api_player_profile failed; returning sample")
        sample = {
            "info": [
                {
                    "PERSON_ID": player_id,
                    "DISPLAY_FIRST_LAST": "Sample Player",
                    "TEAM_NAME": "Sample Team",
                    "JERSEY": "0",
                    "POSITION": "G",
                    "HEIGHT": "6-5",
                    "WEIGHT": "200",
                    "AGE": 25,
                    "PTS": 20.1,
                    "REB": 5.2,
                    "AST": 6.3
                }
            ]
        }
        return jsonify(sample)

# ---------------------------
# API: /api/player/<player_id>/gamelog
# ---------------------------
@app.route('/api/player/<int:player_id>/gamelog')
def api_player_gamelog(player_id):
    try:
        if NBA_API_AVAILABLE:
            gl = playergamelog.PlayerGameLog(player_id=player_id, season=CURRENT_SEASON)
            df = gl.get_data_frames()[0]
            recs = safe_records_from_df(df)
            return jsonify(recs)
        else:
            raise RuntimeError("nba_api not available")
    except Exception as e:
        app.logger.exception("api_player_gamelog failed; returning sample")
        sample = [
            {"GAME_DATE":"2025-11-01","MATCHUP":"LAL vs GSW","PTS":28,"REB":6,"AST":7,"MIN":"35:00"},
            {"GAME_DATE":"2025-10-29","MATCHUP":"LAL @ BOS","PTS":14,"REB":4,"AST":3,"MIN":"28:12"}
        ]
        return jsonify(sample)

# ---------------------------
# API: /api/game/<game_id>/boxscore
# ---------------------------
@app.route('/api/game/<game_id>/boxscore')
def api_game_boxscore(game_id):
    try:
        if NBA_API_AVAILABLE:
            # Try advanced boxscore then traditional
            adv = boxscoreadvancedv3.BoxScoreAdvancedV3(game_id=game_id).get_data_frames()
            trad = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id).get_data_frames()
            # This is a simplified aggregator: player stats from trad[0], team stats from trad[1]
            player_stats = trad[0].to_dict(orient='records') if trad and len(trad) > 0 else []
            team_stats = trad[1].to_dict(orient='records') if trad and len(trad) > 1 else []
            return jsonify({"playerStats": player_stats, "teamStats": team_stats})
        else:
            raise RuntimeError("nba_api not available")
    except Exception as e:
        app.logger.exception("api_game_boxscore failed; returning sample")
        sample = {
            "playerStats": [
                {
                    "personId": 201939,
                    "playerName": "Stephen Curry",
                    "teamTricode": "GSW",
                    "minutes": "36:12",
                    "points": 34,
                    "reboundsTotal": 5,
                    "assists": 8,
                    "steals": 2,
                    "blocks": 0,
                    "fieldGoalsMade": 12,
                    "fieldGoalsAttempted": 23,
                    "threePointersMade": 7,
                    "threePointersAttempted": 13,
                    "freeThrowsMade": 3,
                    "freeThrowsAttempted": 3,
                    "turnovers": 2,
                    "plusMinusPoints": 10,
                    "offensiveRating": 120.5,
                    "defensiveRating": 95.3,
                    "netRating": 25.2,
                    "trueShootingPercentage": 0.66,
                    "usagePercentage": 0.32,
                    "assistPercentage": 0.28,
                    "turnoverRatio": 10.4,
                    "playerImageUrl": f"https://cdn.nba.com/headshots/nba/latest/1040x760/201939.png"
                }
            ],
            "teamStats": [
                {
                    "teamTricode": "GSW",
                    "teamName": "Golden State Warriors",
                    "points": 108,
                    "reboundsTotal": 44,
                    "assists": 25,
                    "steals": 6,
                    "blocks": 4,
                    "fieldGoalsMade": 39,
                    "fieldGoalsAttempted": 92,
                    "threePointersMade": 14,
                    "threePointersAttempted": 39,
                    "freeThrowsMade": 16,
                    "freeThrowsAttempted": 21,
                    "turnovers": 12
                },
                {
                    "teamTricode": "LAL",
                    "teamName": "Los Angeles Lakers",
                    "points": 112,
                    "reboundsTotal": 48,
                    "assists": 22,
                    "steals": 5,
                    "blocks": 6,
                    "fieldGoalsMade": 41,
                    "fieldGoalsAttempted": 90,
                    "threePointersMade": 10,
                    "threePointersAttempted": 30,
                    "freeThrowsMade": 20,
                    "freeThrowsAttempted": 26,
                    "turnovers": 14
                }
            ]
        }
        return jsonify(sample)

# ---------------------------
# API: player accolades (optional)
# ---------------------------
@app.route('/api/player/<int:player_id>/accolades')
def api_player_accolades(player_id):
    try:
        accolades = load_accolades()
        # try by id then by name fallback via commonplayerinfo
        if str(player_id) in accolades:
            return jsonify({"accolades": accolades[str(player_id)]})
        if NBA_API_AVAILABLE:
            p = commonplayerinfo.CommonPlayerInfo(player_id=player_id).get_data_frames()[0]
            name = p.get('DISPLAY_FIRST_LAST').iloc[0] if 'DISPLAY_FIRST_LAST' in p.columns else None
            if name and name in accolades:
                return jsonify({"accolades": accolades[name]})
        return jsonify({"accolades": []})
    except Exception:
        return jsonify({"accolades": []})

# ---------------------------
# Run server
# ---------------------------
if __name__ == '__main__':
    import sys

    # Default port:
    port = 5000

    # Allow override: python api.py --port 8000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    app.run(host='127.0.0.1', port=port, debug=True)

