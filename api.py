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
import re
from datetime import datetime, timedelta, timezone # <-- ADDED TIMEZONE
from flask import Flask, jsonify, render_template, send_from_directory
from flask_cors import CORS
import pandas as pd
import requests # <-- ADDED REQUESTS

# Try importing nba_api modules; if not available, endpoints will fall back.
try:
    from nba_api.stats.static import teams as teams_static
    from nba_api.stats.endpoints import (
        # scoreboardv2, <-- REMOVED
        leaguestandingsv3,
        leaguedashplayerstats,
        commonteamroster,
        commonplayerinfo,
        playergamelog,
        # teamgamelog, <-- REMOVED
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
        if key in _CACHE: # Check if key exists before deleting
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
    
    # --- *** FIX for ValueError: Columns must be same length as key *** ---
    # Use a loop-based fillna which is more robust than the
    # vectorized assignment that was causing the error.
    numeric_cols = df.select_dtypes(include='number').columns
    for col in numeric_cols:
        df[col] = df[col].fillna(0)
    
    object_cols = df.select_dtypes(include='object').columns
    for col in object_cols:
        df[col] = df[col].fillna("")
    # --- *** END FIX *** ---
    
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
    """
    FIXED: Replaced scoreboardv2 with a direct call to NBA CDN.
    This is more reliable and faster.
    """
    cached = cache_get('scoreboard')
    if cached:
        return jsonify(cached)
    try:
        # Fetch directly from the NBA's CDN
        url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
        res = requests.get(url, timeout=5)
        res.raise_for_status() # Fail fast if the URL is down
        data = res.json().get('scoreboard', {})
        
        cdn_games = data.get('games', [])
        unified = []
        
        for g in cdn_games:
            # Transform the CDN data into the format the frontend expects
            home_team = g.get('homeTeam', {})
            away_team = g.get('awayTeam', {})
            
            # Format the start time
            start_time_str = g.get('gameEt', '1970-01-01T00:00:00Z')
            
            unified.append({
                "gameId": g.get('gameId'), # This is the nba_api compatible ID
                "gameStatus": g.get('gameStatusText'),
                "homeTeamId": home_team.get('teamId'),
                "awayTeamId": away_team.get('teamId'),
                "homeTeam": home_team.get('teamCity') + " " + home_team.get('teamName'),
                "awayTeam": away_team.get('teamCity') + " " + away_team.get('teamName'),
                "homeAbbr": home_team.get('teamTricode'),
                "awayAbbr": away_team.get('teamTricode'),
                "homeLogo": f"https://cdn.nba.com/logos/nba/{home_team.get('teamId')}/global/L/logo.svg" if home_team.get('teamId') else "/static/logo.png",
                "awayLogo": f"https://cdn.nba.com/logos/nba/{away_team.get('teamId')}/global/L/logo.svg" if away_team.get('teamId') else "/static/logo.png",
                "homeScore": home_team.get('score'),
                "awayScore": away_team.get('score'),
                "startTimeUTC": start_time_str,
                "arena": g.get('arena', {}).get('name', '')
            })
            
        out = {"games": unified}
        cache_set('scoreboard', out, ttl=15) # Cache for 15 seconds
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
            # FIX: Ensure PERSON_ID is included for frontend links
            out[stat] = [{"PLAYER": r.get('PLAYER_NAME') or r.get('PLAYER'), "TEAM": r.get('abbreviation'), stat: r.get(stat), "PERSON_ID": r.get('PLAYER_ID')} for r in merged.to_dict(orient='records')]
        cache_set('leaders_home', out, ttl=30)
        return jsonify(out)
    except Exception as e:
        app.logger.exception("api_leaders_home failed; returning sample")
        sample = {
            "PTS": [{"PLAYER":"L. James","TEAM":"LAL","PTS":30.1, "PERSON_ID": 2544},{"PLAYER":"S. Curry","TEAM":"GSW","PTS":29.4, "PERSON_ID": 201939}],
            "REB": [{"PLAYER":"N. Jokic","TEAM":"DEN","REB":11.2, "PERSON_ID": 203999},{"PLAYER":"G. Antetokounmpo","TEAM":"MIL","REB":10.8, "PERSON_ID": 203507}],
            "AST": [{"PLAYER":"L. Doncic","TEAM":"DAL","AST":9.8, "PERSON_ID": 1629029},{"PLAYER":"C. Paul","TEAM":"PHX","AST":8.9, "PERSON_ID": 101108}]
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
# ---------------------------
# API: /api/team/<team_id>/schedule
# ---------------------------
@app.route('/api/team/<int:team_id>/schedule')
def api_team_schedule(team_id):
    """
    FIXED: Re-written to use *only* the reliable NBA CDN schedule feed.
    This avoids all flaky nba_api endpoints for schedules.
    It fetches the one CDN file and filters it for past/upcoming games.
    """
    try:
        # Get full league schedule from CDN (cached for 1 hour)
        cdn_schedule = cache_get('full_schedule_v2') # Use a new cache key
        if not cdn_schedule:
            app.logger.info("Fetching full schedule from NBA CDN...")
            sched_url = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json"
            sched_res = requests.get(sched_url, timeout=5)
            sched_res.raise_for_status()
            cdn_schedule = sched_res.json()
            cache_set('full_schedule_v2', cdn_schedule, ttl=3600)

        # Find all games for this team
        team_games = []
        league_schedule = cdn_schedule.get('leagueSchedule', {})
        for game_date in league_schedule.get('gameDates', []):
            for game in game_date.get('games', []):
                # teamId in CDN is an integer
                if game.get('homeTeam', {}).get('teamId') == team_id or \
                    game.get('awayTeam', {}).get('teamId') == team_id:
                    team_games.append(game)
        
        if not team_games:
            app.logger.warning(f"No games found in CDN schedule for team {team_id}.")
            return jsonify({"upcoming": [], "recent": []})

        # --- *** FIX: Helper to parse game time, returns None on failure *** ---
        def get_game_time(g):
            game_time_str = g.get('gameEt') # Get value, no default
            if not game_time_str: # Check for None or ""
                return None # Return None if no date
            try:
                return datetime.fromisoformat(game_time_str.replace('Z', '+00:00'))
            except ValueError:
                try:
                    # Fallback for other formats
                    return datetime.strptime(game_time_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                except Exception:
                    return None # Return None if all parsing fails

        # Sort all games by date (games with no time will be first/last)
        team_games.sort(key=lambda g: get_game_time(g) or datetime.min.replace(tzinfo=timezone.utc))
        
        # Split into upcoming and recent
        upcoming_games_raw = []
        recent_games_raw = []
        today = datetime.now(timezone.utc)

        for g in team_games:
            game_time = get_game_time(g)
            # Use game time if available, otherwise check game status
            if game_time and game_time > today and g.get('gameStatusText') != 'Final':
                upcoming_games_raw.append(g)
            elif g.get('gameStatusText') == 'Final':
                recent_games_raw.append(g)
            elif not game_time and g.get('gameStatusText') != 'Final':
                # No time, not final -> Upcoming
                upcoming_games_raw.append(g)

        # Helper to format game for frontend
        def format_game(g, is_recent=False):
            home = g['homeTeam']
            away = g['awayTeam']
            matchup_str = f"{away['teamTricode']} @ {home['teamTricode']}"
            game_time_obj = get_game_time(g)

            game_data = {
                "GAME_ID": g['gameId'],
                # --- *** FIX: Send null if obj is None, else send ISO string *** ---
                "GAME_DATETIME": game_time_obj.isoformat() if game_time_obj else None,
                # --- *** FIX: Add a fallback date string *** ---
                "GAME_DATE_STR": g.get('gameDateEst', 'Date TBD'), # e.g., "2025-11-14T00:00:00Z"
                "MATCHUP": matchup_str,
                "WL": None, # Default
            }
            if is_recent:
                # Determine WL for the requested team
                team_score = home['score'] if home['teamId'] == team_id else away['score']
                opp_score = away['score'] if home['teamId'] == team_id else home['score']
                game_data['WL'] = 'W' if team_score > opp_score else 'L'
                game_data['PTS'] = team_score
                game_data['OPP_PTS'] = opp_score
            return game_data

        # Get last 5 recent, first 5 upcoming
        recent_games = [format_game(g, is_recent=True) for g in recent_games_raw[-5:]]
        recent_games.reverse() # Show most recent first
        upcoming_games = [format_game(g) for g in upcoming_games_raw[:5]]

        return jsonify({
            "upcoming": upcoming_games,
            "recent": recent_games
        })

    except Exception as e:
        app.logger.error("api_team_schedule failed completely: %s", e)
        sample = {
            "upcoming": [
                {"GAME_ID": "1001", "GAME_DATETIME": "2025-04-10T19:30:00", "MATCHUP": "LAL vs GSW", "WL": None}
            ],
            "recent": [
                {"GAME_ID": "999", "GAME_DATETIME": "2025-04-08T19:30:00", "MATCHUP": "LAL @ BOS", "WL": "L", "PTS": 100, "OPP_PTS": 110}
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
                # Also get headline stats
                if len(info) > 1:
                    df_stats = info[1]
                    # Merge stats into info df
                    if not df_stats.empty:
                        stats_row = df_stats.iloc[0]
                        df_info['PTS'] = stats_row.get('PTS')
                        df_info['REB'] = stats_row.get('REB')
                        df_info['AST'] = stats_row.get('AST')
                
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
# *** NEW HELPER FUNCTIONS for CDN box score ***
# ---------------------------
# ---------------------------
# *** NEW HELPER FUNCTIONS for CDN box score ***
# ---------------------------
def _format_cdn_player(p, team_tricode):
    # Helper to format a player obj from CDN to what frontend expects
    stats = p.get('statistics', {})
    
    # --- FIX FOR MINUTES ---
    minutes_str = stats.get('minutes', 'PT0M0S') # Get the raw string
    min_formatted = '00:00' # Default
    if minutes_str and 'PT' in minutes_str:
        try:
            # Use regex to find M (minutes) and S (seconds) values
            match = re.match(r'PT(?:(\d+)M)?(?:(\d+)\.?\d*S)?', minutes_str)
            if match:
                mins = match.group(1) or '0'
                secs = match.group(2) or '0'
                # Format as MM:SS with leading zeros
                min_formatted = f"{mins.zfill(2)}:{secs.zfill(2)}"
        except Exception:
            pass # If parsing fails, it will just show '00:00'
    # --- END FIX ---

    return {
        "personId": p.get('personId'),
        # --- FIX FOR NAME: Use 'name' field, which is the full name ---
        "playerName": p.get('name', p.get('firstName', '') + ' ' + p.get('lastName', '')),
        "teamTricode": team_tricode,
        "minutes": min_formatted, # Use the new formatted string
        "points": stats.get('points'),
        "reboundsTotal": stats.get('reboundsTotal'),
        "assists": stats.get('assists'),
        "steals": stats.get('steals'),
        "blocks": stats.get('blocks'),
        "fieldGoalsMade": stats.get('fieldGoalsMade'),
        "fieldGoalsAttempted": stats.get('fieldGoalsAttempted'),
        "threePointersMade": stats.get('threePointersMade'),
        "threePointersAttempted": stats.get('threePointersAttempted'),
        "freeThrowsMade": stats.get('freeThrowsMade'),
        "freeThrowsAttempted": stats.get('freeThrowsAttempted'),
        "turnovers": stats.get('turnovers'),
        "plusMinusPoints": stats.get('plusMinusPoints'),
        "playerImageUrl": f"https://cdn.nba.com/headshots/nba/latest/1040x760/{p.get('personId')}.png"
    }

def _format_cdn_team(t):
    # Helper to format a team obj from CDN to what frontend expects
    stats = t.get('statistics', {})
    return {
        "teamTricode": t.get('teamTricode'),
        "teamName": t.get('teamName'),
        "points": stats.get('points'),
        "reboundsTotal": stats.get('reboundsTotal'),
        "assists": stats.get('assists'),
        "steals": stats.get('steals'),
        "blocks": stats.get('blocks'),
        "fieldGoalsMade": stats.get('fieldGoalsMade'),
        "fieldGoalsAttempted": stats.get('fieldGoalsAttempted'),
        "threePointersMade": stats.get('threePointersMade'),
        "threePointersAttempted": stats.get('threePointersAttempted'),
        "freeThrowsMade": stats.get('freeThrowsMade'),
        "freeThrowsAttempted": stats.get('freeThrowsAttempted'),
        "turnovers": stats.get('turnovers'),
    }

# ---------------------------
# API: /api/game/<game_id>/boxscore
# ---------------------------
@app.route('/api/game/<game_id>/boxscore')
def api_game_boxscore(game_id):
    """
    *** NEW CDN-BASED FUNCTION ***
    Fetches boxscore directly from NBA's liveData CDN.
    This is more reliable than the nba_api library endpoints
    and fixes both missing names and duplicate team stats.
    """
    try:
        # 1. Fetch data from CDN
        url = f"https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"
        res = requests.get(url, timeout=5)
        res.raise_for_status() # Fail fast if game_id is bad
        
        data = res.json()
        game = data.get('game')
        
        if not game:
            app.logger.error(f"Game {game_id}: CDN JSON response was empty or malformed.")
            raise RuntimeError("CDN data was empty")

        home_team = game.get('homeTeam', {})
        away_team = game.get('awayTeam', {})

        # 2. Process Player Stats
        player_stats = []
        
        # Get Away Team Players
        for p in away_team.get('players', []):
            # Only add players who actually played
            if p.get('status') == 'ACTIVE' and p.get('statistics', {}).get('minutes') and p.get('statistics', {}).get('minutes') != '00:00':
                player_stats.append(_format_cdn_player(p, away_team.get('teamTricode')))
        
        # Get Home Team Players
        for p in home_team.get('players', []):
            if p.get('status') == 'ACTIVE' and p.get('statistics', {}).get('minutes') and p.get('statistics', {}).get('minutes') != '00:00':
                player_stats.append(_format_cdn_player(p, home_team.get('teamTricode')))

        # 3. Process Team Stats (Finals only, no duplicates)
        team_stats = []
        if away_team.get('statistics'):
            team_stats.append(_format_cdn_team(away_team))
        if home_team.get('statistics'):
            team_stats.append(_format_cdn_team(home_team))
        
        return jsonify({"playerStats": player_stats, "teamStats": team_stats})

    except Exception as e:
        app.logger.exception("api_game_boxscore (CDN) failed; returning sample")
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
            try:
                port = int(sys.argv[idx + 1])
            except ValueError:
                app.logger.error(f"Invalid port: {sys.argv[idx + 1]}. Using default 5000.")


    app.run(host='127.0.0.1', port=port, debug=True)