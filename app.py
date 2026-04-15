import io
import base64
import matplotlib
import math  # Added for rounding up match estimates
matplotlib.use('Agg') # Required for Flask/Non-interactive mode
import matplotlib.pyplot as plt
from flask import Flask, render_template, request, redirect, jsonify, session
import sqlite3

app = Flask(__name__)
app.secret_key = "cricvision_secure_key"
# =====================================================
# ================= DATABASE SETUP ====================
# =====================================================

def init_db():
    conn = sqlite3.connect("cricket.db")
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        team TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER,
        opponent TEXT,
        runs INTEGER DEFAULT 0,
        balls INTEGER DEFAULT 0,
        fours INTEGER DEFAULT 0,
        sixes INTEGER DEFAULT 0,
        wickets INTEGER DEFAULT 0,
        runs_conceded INTEGER DEFAULT 0,
        overs REAL DEFAULT 0.0,
        FOREIGN KEY(player_id) REFERENCES players(id)
    )
    """)

    conn.commit()
    conn.close()
    fix_existing_over_data() # Automatically fixes your 0.9, 1.9 data on startup

def fix_existing_over_data():
    """Corrects data already entered using 10-ball logic (e.g., 0.9 -> 1.3)"""
    conn = sqlite3.connect("cricket.db")
    cursor = conn.cursor()
    rows = cursor.execute("SELECT id, overs FROM performance").fetchall()
    for row_id, overs in rows:
        overs_str = str(overs)
        if '.' in overs_str:
            balls = int(overs_str.split('.')[1])
            if balls >= 6:
                main_over = int(float(overs_str.split('.')[0]))
                # Corrects 0.6 to 1.0, 0.9 to 1.3
                new_overs = main_over + 1 + (balls - 6) / 10
                cursor.execute("UPDATE performance SET overs = ? WHERE id = ?", (new_overs, row_id))
    conn.commit()
    conn.close()

def get_connection():
    conn = sqlite3.connect("cricket.db")
    conn.row_factory = sqlite3.Row
    return conn

def get_total_balls_from_overs(overs_val):
    """Converts cricket notation to total balls (e.g. 1.1 -> 7 balls)"""
    full_overs = int(overs_val)
    extra_balls = round((overs_val - full_overs) * 10)
    return (full_overs * 6) + extra_balls

# =====================================================
# ================= FIXED 10 TEAMS ====================
# =====================================================

TEAMS = [
    "Mumbai Indians","Rajastan Royals","Gujarat Titans","Lucknow Super Giants","Chennai Super kings",
    "Royal Challengers Banglore","Sunrisers Hydreabad","Delhi Capitals","Kolkata Knight Riders",
    "Punjab Kings"
]

# =====================================================
# ================= AI LOGIC FEATURE ==================
# =====================================================

def get_ai_prediction(player_role, performances):
    if not performances or len(performances) < 1:
        return "Not Enough Data"
    
    recent_perf = performances[-3:] 
    
    if len(recent_perf) == 3:
        weights = [0.2, 0.3, 0.5]
    elif len(recent_perf) == 2:
        weights = [0.4, 0.6]
    else:
        weights = [1.0]

    role = player_role.lower()

    if "batter" in role:
        vals = [p["runs"] for p in recent_perf]
        prediction = sum(v * w for v, w in zip(vals, weights))
        return f"~{round(prediction)} Runs"

    elif "bowler" in role:
        vals = [p["wickets"] for p in recent_perf]
        prediction = sum(v * w for v, w in zip(vals, weights))
        return f"~{round(prediction)} Wickets" # Removed decimal

    elif "all rounder" in role or "all-rounder" in role:
        r_vals = [p["runs"] for p in recent_perf]
        w_vals = [p["wickets"] for p in recent_perf]
        pred_r = sum(v * w for v, w in zip(r_vals, weights))
        pred_w = sum(v * w for v, w in zip(w_vals, weights))
        return f"{round(pred_r)} Runs & {round(pred_w)} Wkts" # Removed decimal

    return "N/A"

# =====================================================
# ============= NEW: MILESTONE TRACKER ================
# =====================================================

def get_milestones(stats, prediction_text, role):
    milestones = []
    role = role.lower()
    
    # Batting Milestones
    if "batter" in role or "all rounder" in role or "all-rounder" in role:
        current_runs = stats['runs']
        next_run_goal = ((current_runs // 100) + 1) * 100
        runs_needed = next_run_goal - current_runs
        
        msg = f"Needs {runs_needed} more runs to reach {next_run_goal} career runs"
        
        # Estimate matches based on AI prediction
        if "Runs" in prediction_text:
            try:
                # Extract number from "~45 Runs" or "45 Runs & 1.2 Wkts"
                pred_val = float(prediction_text.split(" Runs")[0].replace("~", ""))
                if pred_val > 0:
                    matches = math.ceil(runs_needed / pred_val) # Fixed decimal (rounds up)
                    msg += f" (Est. {matches} matches)"
            except: pass
        milestones.append(msg)

    # Bowling Milestones
    if "bowler" in role or "all rounder" in role or "all-rounder" in role:
        current_wickets = stats['wickets']
        next_wk_goal = ((current_wickets // 10) + 1) * 10
        wks_needed = next_wk_goal - current_wickets
        
        msg = f"Needs {wks_needed} more wickets to reach {next_wk_goal} career wickets"
        
        # Estimate matches
        if "Wkts" in prediction_text or "Wickets" in prediction_text:
            try:
                # Extract number from "~1.2 Wickets" or "45 Runs & 1.2 Wkts"
                part = prediction_text.split("&")[-1] if "&" in prediction_text else prediction_text
                pred_val = float(part.replace("~", "").replace(" Wkts", "").replace(" Wickets", "").strip())
                if pred_val > 0:
                    matches = math.ceil(wks_needed / pred_val) # Fixed decimal (rounds up)
                    msg += f" (Est. {matches} matches)"
            except: pass
        milestones.append(msg)

    return milestones


# =====================================================
# ===================== ROUTES ========================
# =====================================================

@app.route('/')
def home():
    return render_template("home.html")

@app.route('/squad')
def squad():
    return render_template("squad.html", teams=TEAMS)

@app.route('/team/<team_name>')
def team_players(team_name):
    conn = get_connection()
    players = conn.execute("SELECT * FROM players WHERE team=?", (team_name,)).fetchall()
    conn.close()
    return render_template("team_players.html", players=players, team_name=team_name)

def get_player_stats(player_id):
    conn = get_connection()
    performances = conn.execute("SELECT * FROM performance WHERE player_id=?", (player_id,)).fetchall()

    total_runs = 0
    total_balls_faced = 0
    total_wickets = 0
    total_runs_conceded = 0
    total_balls_bowled = 0
    total_matches = len(performances)

    for p in performances:
        total_runs += p["runs"]
        total_balls_faced += p["balls"]
        total_wickets += p["wickets"]
        total_runs_conceded += int(p["runs_conceded"])
        # Correctly convert overs like 0.6 or 0.9 into actual ball count
        total_balls_bowled += get_total_balls_from_overs(p["overs"])

    strike_rate = round((total_runs / total_balls_faced * 100), 2) if total_balls_faced > 0 else 0
    average = round((total_runs / total_matches), 2) if total_matches > 0 else 0
    
    # Accurate Economy using ball count
    economy = round((total_runs_conceded / (total_balls_bowled / 6.0)), 2) if total_balls_bowled > 0 else 0
    bowling_sr = round((total_balls_bowled / total_wickets), 2) if total_wickets > 0 else 0

    conn.close()

    return {
        "matches": total_matches,
        "runs": total_runs,
        "strike_rate": strike_rate,
        "average": average,
        "wickets": total_wickets,
        "economy": economy,
        "bowling_sr": bowling_sr
    }

@app.route('/player/<int:player_id>')
def player(player_id):
    conn = get_connection()
    player_data = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    
    if not player_data:
        conn.close()
        return "Player not found", 404

    performances = conn.execute(
        "SELECT id, opponent, runs, balls, wickets, runs_conceded, overs FROM performance WHERE player_id=? ORDER BY id ASC",
        (player_id,)
    ).fetchall()
    conn.close()

    stats = get_player_stats(player_id)
    ai_prediction = get_ai_prediction(player_data['role'], performances)
    milestones = get_milestones(stats, ai_prediction, player_data['role'])

    opponents = [p["opponent"] for p in performances]
    runs_list = [p["runs"] for p in performances]
    wickets_list = [p["wickets"] for p in performances]

    plot_url = None
    if opponents:
        plt.figure(figsize=(10, 5), facecolor='#1e3a8a')
        ax1 = plt.gca()
        ax1.set_facecolor('#0f172a')
        
        role = player_data['role'].lower()

        if 'all rounder' in role:
            ax1.plot(opponents, runs_list, color='#3b82f6', marker='o', linewidth=3, label='Runs')
            ax2 = ax1.twinx()
            ax2.bar(opponents, wickets_list, color='#fbbf24', alpha=0.4, label='Wickets')
        elif 'bowler' in role:
            plt.bar(opponents, wickets_list, color='#fbbf24', alpha=0.8)
        else:
            plt.plot(opponents, runs_list, marker='o', color='#3b82f6', linewidth=3)
            plt.fill_between(opponents, runs_list, color='#3b82f6', alpha=0.3)

        plt.xticks(rotation=45, color='white')
        plt.yticks(color='white')
        
        img = io.BytesIO()
        plt.savefig(img, format='png', bbox_inches='tight', facecolor='#1e3a8a')
        img.seek(0)
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
        plt.close()

    return render_template("player_stats.html", 
                           player=player_data, 
                           stats=stats, 
                           performances=performances, 
                           plot_url=plot_url,
                           prediction=ai_prediction,
                           milestones=milestones)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == "1856":
            session['admin_logged_in'] = True
            return redirect('/admin')
        return render_template("login.html", error="Invalid Credentials")
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect('/login')

@app.route('/admin')
def admin():
    # 1. Security Check: Redirect to login if the session is not set
    if not session.get('admin_logged_in'):
        return redirect('/login')

    # 2. Existing Database Logic
    conn = get_connection()
    players = conn.execute("SELECT * FROM players").fetchall()
    all_performances = conn.execute("""
        SELECT p.*, pl.name as player_name 
        FROM performance p 
        JOIN players pl ON p.player_id = pl.id 
        ORDER BY p.id DESC
    """).fetchall()
    conn.close()
    
    # 3. Render the Admin Page
    return render_template("admin.html", 
                           players=players, 
                           teams=TEAMS, 
                           all_performances=all_performances)

@app.route('/add_player', methods=['POST'])
def add_player():
    name = request.form['name']
    role = request.form['role']
    team = request.form['team']
    conn = get_connection()
    conn.execute("INSERT INTO players (name, role, team) VALUES (?, ?, ?)", (name, role, team))
    conn.commit()
    conn.close()
    return redirect('/admin')

@app.route('/add_performance', methods=['POST'])
def add_performance():
    player_id = request.form['player_id']
    opponent = request.form['opponent']
    runs = request.form.get('runs', 0)
    balls = request.form.get('balls', 0)
    fours = request.form.get('fours', 0)
    sixes = request.form.get('sixes', 0)
    wickets = request.form.get('wickets', 0)
    runs_conceded = request.form.get('runs_conceded', 0)
    overs = request.form.get('overs', 0.0)

    conn = get_connection()
    conn.execute("""
        INSERT INTO performance 
        (player_id, opponent, runs, balls, fours, sixes, wickets, runs_conceded, overs) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (player_id, opponent, runs, balls, fours, sixes, wickets, runs_conceded, overs))
    conn.commit()
    conn.close()
    return redirect('/admin')

@app.route('/edit_performance/<int:performance_id>', methods=['GET', 'POST'])
def edit_performance(performance_id):
    conn = get_connection()
    if request.method == 'POST':
        opponent = request.form['opponent']
        runs = request.form['runs']
        balls = request.form['balls']
        fours = request.form['fours']
        sixes = request.form['sixes']
        wickets = request.form['wickets']
        runs_conceded = request.form['runs_conceded']
        overs = request.form['overs']
        
        conn.execute('''UPDATE performance 
                        SET opponent=?, runs=?, balls=?, fours=?, sixes=?, wickets=?, runs_conceded=?, overs=? 
                        WHERE id=?''', 
                     (opponent, runs, balls, fours, sixes, wickets, runs_conceded, overs, performance_id))
        conn.commit()
        conn.close()
        return redirect('/admin')

    performance = conn.execute('''
        SELECT p.*, pl.role 
        FROM performance p 
        JOIN players pl ON p.player_id = pl.id 
        WHERE p.id = ?''', (performance_id,)).fetchone()
    
    conn.close()
    return render_template('edit_performance.html', p=performance)

@app.route('/edit_player/<int:player_id>', methods=['GET', 'POST'])
def edit_player(player_id):
    conn = get_connection()
    if request.method == 'POST':
        name = request.form['name']
        role = request.form['role']
        team = request.form['team']
        conn.execute("UPDATE players SET name=?, role=?, team=? WHERE id=?", (name, role, team, player_id))
        conn.commit()
        conn.close()
        return redirect('/admin')
    player = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    conn.close()
    return render_template("edit_player.html", player=player, teams=TEAMS)

@app.route('/delete_player/<int:player_id>')
def delete_player(player_id):
    conn = get_connection()
    conn.execute("DELETE FROM players WHERE id=?", (player_id,))
    conn.execute("DELETE FROM performance WHERE player_id=?", (player_id,))
    conn.commit()
    conn.close()
    return redirect('/admin')



@app.route('/compare', methods=['GET', 'POST'])
def compare():
    conn = get_connection()
    
    if request.method == 'POST':
        p1_id = request.form.get('player1')
        p2_id = request.form.get('player2')
        
        if not p1_id or not p2_id or p1_id == p2_id:
            return "Invalid Selection: Please select two different players.", 400

        p1_data = conn.execute("SELECT * FROM players WHERE id=?", (p1_id,)).fetchone()
        p2_data = conn.execute("SELECT * FROM players WHERE id=?", (p2_id,)).fetchone()
        
        if p1_data['role'] != p2_data['role']:
            return "Error: You can only compare players with the same role.", 400

        p1_stats = get_player_stats(p1_id)
        p2_stats = get_player_stats(p2_id)
        
        p1_perf = conn.execute("SELECT * FROM performance WHERE player_id=?", (p1_id,)).fetchall()
        p2_perf = conn.execute("SELECT * FROM performance WHERE player_id=?", (p2_id,)).fetchall()
        
        p1_pred = get_ai_prediction(p1_data['role'], p1_perf)
        p2_pred = get_ai_prediction(p2_data['role'], p2_perf)

        def calculate_ai_score(stats, prediction, role):
            try:
                clean_pred = float(prediction.split()[0].replace("~", ""))
                if "bowler" in role.lower():
                    return (stats['wickets'] * 0.4) + (clean_pred * 0.6)
                else:
                    return (stats['average'] * 0.4) + (clean_pred * 0.6)
            except: return 0

        p1_score = calculate_ai_score(p1_stats, p1_pred, p1_data['role'])
        p2_score = calculate_ai_score(p2_stats, p2_pred, p2_data['role'])
        
        winner = p1_data['name'] if p1_score > p2_score else p2_data['name']
        if p1_score == p2_score: winner = "It's a Tie!"

        conn.close()
        return render_template("comparison_result.html", 
                               p1=p1_data, p2=p2_data, 
                               s1=p1_stats, s2=p2_stats,
                               pr1=p1_pred, pr2=p2_pred,
                               winner=winner)

    players = conn.execute("SELECT id, name, team, role FROM players ORDER BY name ASC").fetchall()
    conn.close()
    return render_template("compare_select.html", players=players)

@app.route('/leaderboards')
def leaderboards():
    conn = get_connection()
    conn.row_factory = sqlite3.Row 
    
    # Updated Base Query to calculate balls correctly from overs logic
    base_query = """
        SELECT p.id, p.name, p.team, 
                SUM(COALESCE(perf.runs, 0)) as total_runs, 
                SUM(COALESCE(perf.sixes, 0)) as total_sixes, 
                SUM(COALESCE(perf.fours, 0)) as total_fours, 
                SUM(COALESCE(perf.wickets, 0)) as total_wickets,
                SUM(COALESCE(perf.balls, 0)) as total_balls,
                SUM(COALESCE(perf.runs_conceded, 0)) as total_runs_conceded,
                SUM(CAST(COALESCE(perf.overs, 0) AS INT) * 6 + (COALESCE(perf.overs, 0) - CAST(COALESCE(perf.overs, 0) AS INT)) * 10) as total_balls_bowled
        FROM players p
        LEFT JOIN performance perf ON p.id = perf.player_id
        GROUP BY p.id
    """

    most_runs = conn.execute(f"SELECT * FROM ({base_query}) ORDER BY total_runs DESC LIMIT 5").fetchall()
    most_sixes = conn.execute(f"SELECT * FROM ({base_query}) ORDER BY total_sixes DESC LIMIT 5").fetchall()
    most_fours = conn.execute(f"SELECT * FROM ({base_query}) ORDER BY total_fours DESC LIMIT 5").fetchall()

    best_sr = conn.execute(f"""
        SELECT *, (CAST(total_runs AS FLOAT) / NULLIF(total_balls, 0) * 100) AS strike_rate 
        FROM ({base_query}) 
        WHERE total_balls > 0 
        ORDER BY strike_rate DESC LIMIT 5
    """).fetchall()

    best_avg = conn.execute(f"""
        SELECT p_outer.*, 
        (CAST(p_outer.total_runs AS FLOAT) / NULLIF(
            (SELECT COUNT(*) FROM performance WHERE player_id = p_outer.id), 0
        )) AS average 
        FROM ({base_query}) AS p_outer
        WHERE p_outer.total_runs > 0 
        ORDER BY average DESC LIMIT 5
    """).fetchall()

    most_wickets = conn.execute(f"SELECT * FROM ({base_query}) ORDER BY total_wickets DESC LIMIT 5").fetchall()

    # Economy uses total_balls_bowled correctly
    best_eco = conn.execute(f"""
        SELECT *, 
        (CAST(total_runs_conceded AS FLOAT) / NULLIF((total_balls_bowled / 6.0), 0)) AS economy_rate 
        FROM ({base_query}) 
        WHERE total_balls_bowled >= 6
        ORDER BY economy_rate ASC LIMIT 5
    """).fetchall()
    
    conn.close()
    
    return render_template("leaderboards.html", 
                           runs=most_runs, sixes=most_sixes, fours=most_fours,
                           sr=best_sr, avg=best_avg, 
                           wickets=most_wickets, eco=best_eco)

@app.route('/simulate_matchup', methods=['POST'])
def simulate_matchup():
    data = request.get_json()
    bat_id = data.get('batter_id')
    bowl_id = data.get('bowler_id')

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    
    bat = conn.execute("""
        SELECT SUM(COALESCE(runs, 0)) as r, SUM(COALESCE(balls, 0)) as b 
        FROM performance WHERE player_id = ?""", (bat_id,)).fetchone()
    
    bowl_data = conn.execute("""
        SELECT SUM(COALESCE(runs_conceded, 0)) as rc, 
               SUM(CAST(COALESCE(overs, 0) AS INT) * 6 + (COALESCE(overs, 0) - CAST(COALESCE(overs, 0) AS INT)) * 10) as tb 
        FROM performance WHERE player_id = ?""", (bowl_id,)).fetchone()
    conn.close()

    bat_sr = (bat['r'] / bat['b'] * 100) if bat and bat['b'] > 0 else 100
    bowl_eco = (bowl_data['rc'] / (bowl_data['tb'] / 6.0)) if bowl_data and bowl_data['tb'] > 0 else 6.0
    
    win_chance = round((bat_sr / (bat_sr + (bowl_eco * 16.6))) * 100, 1)

    return jsonify({
        "chance": win_chance,
        "verdict": "Batter Favoured" if win_chance > 52 else "Bowler Favoured" if win_chance < 48 else "Even Fight"
    })

    

if __name__ == "__main__":
    init_db()
    app.run(debug=True, threaded=True)