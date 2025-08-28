import random
import string
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os

# Flask app init
app = Flask(__name__)
app.secret_key = 'hello123'  # Replace with secure key in production

# Enable Flask-SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# ================= Database Config =================
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:  # Example: mysql+pymysql://user:pass@host/db
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:  # Fallback to SQLite (works on Render)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///voting.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# DB init
db = SQLAlchemy(app)

# ================= Login Manager =================
login_manager = LoginManager(app)
login_manager.login_view = 'home'

# ================= Models =================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(50), nullable=False)

class Idea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    score_judge = db.Column(db.Integer, default=0)
    score_audience = db.Column(db.Integer, default=0)
    total_score = db.Column(db.Integer, default=0)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ================= OTP System =================
otp_storage = {}

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def is_otp_expired(stored_otp):
    if not stored_otp or 'expiry_time' not in stored_otp:
        return True
    return time.time() > stored_otp['expiry_time']

# Instead of sending email, just print OTP in console
def send_mail(email, subject, message):
    print(f"📩 OTP for {email}: {message}")  

# ================= Routes =================
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        email = request.form['email']
        role = request.form['role']
        user = User.query.filter_by(email=email, role=role).first()
        if user:
            login_user(user)
            session.permanent = True
            return redirect(url_for(f'{role}_dashboard'))
        flash("Invalid email or role.", "danger")
    return render_template('login.html')

@app.route('/send_otp', methods=['POST'])
def send_otp():
    email = request.form['email']
    role = request.form['role']

    # Allow only company emails (optional)
    if not email.endswith('@amdocs.com'):
        flash("Only @amdocs.com email addresses are allowed!", "danger")
        return redirect(url_for('home'))

    user = User.query.filter_by(email=email).first()

    if role in ["judge", "admin"]:  
        if not user:
            flash("Email not registered!", "danger")
            return redirect(url_for('home'))
        if user.role != role:
            flash("Role mismatch. Please choose correct role.", "danger")
            return redirect(url_for('home'))

    if role == "audience" and not user:
        user = User(email=email, role=role)
        db.session.add(user)
        db.session.commit()

    otp = generate_otp()
    expiry_time = time.time() + 900  # 15 min
    otp_storage[email] = {"otp": otp, "expiry_time": expiry_time}

    subject = "Your OTP Code"
    message = f"Your OTP code is: {otp}"
    send_mail(email, subject, message)

    flash(f"OTP sent to {email} (Check console log).", "success")
    return redirect(url_for('otp_verification', email=email))

@app.route('/otp_verification', methods=['GET', 'POST'])
def otp_verification():
    email = request.args.get('email')

    if request.method == 'POST':
        entered_otp = request.form['otp']
        stored_otp = otp_storage.get(email, None)

        if not stored_otp:
            flash("No OTP found. Please request a new one.", "danger")
            return redirect(url_for('home'))

        if is_otp_expired(stored_otp):
            flash("OTP expired. Please request a new one.", "danger")
            del otp_storage[email]
            return redirect(url_for('home'))

        if entered_otp == stored_otp['otp']:
            del otp_storage[email]
            user = User.query.filter_by(email=email).first()
            if user:
                session['role'] = user.role
                session['user'] = email
                session.permanent = True
                login_user(user)
                return redirect(url_for(f'{user.role}_dashboard'))
            else:
                flash("User not found.", "danger")
                return redirect(url_for('home'))
        else:
            flash("Invalid OTP!", "danger")
            return redirect(url_for('otp_verification', email=email))

    return render_template('otp_verification.html', email=email)

@app.route('/judge_dashboard', methods=['GET', 'POST'])
@login_required
def judge_dashboard():
    if current_user.role != 'judge':
        return redirect(url_for('home'))
    if request.method == 'POST':
        for idea in Idea.query.all():
            score = request.form.get(f"score_{idea.id}")
            if score:
                idea.score_judge += int(score)
                idea.total_score += int(score)
        db.session.commit()
        update_scores()
        return redirect(url_for('thank_you'))
    return render_template('judge_dashboard.html', ideas=Idea.query.all())

@app.route('/audience_dashboard', methods=['GET', 'POST'])
@login_required
def audience_dashboard():
    if current_user.role != 'audience':
        return redirect(url_for('home'))
    if request.method == 'POST':
        for idea in Idea.query.all():
            score = request.form.get(f"score_{idea.id}")
            if score:
                idea.score_audience += int(score)
                idea.total_score += int(score)
        db.session.commit()
        update_scores()
        return redirect(url_for('thank_you'))
    return render_template('audience_dashboard.html', ideas=Idea.query.all())

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('home'))
    ideas = Idea.query.all()
    winner = max(ideas, key=lambda idea: idea.total_score, default=None)
    return render_template('admin_dashboard.html', ideas=ideas, winner=winner)

@app.route('/result')
def result():
    ideas = Idea.query.all()
    return render_template('result.html', total_scores=ideas)

@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

# ================= Real-time Scores =================
def update_scores():
    ideas = Idea.query.all()
    scores = {idea.id: {
        'judge': idea.score_judge,
        'audience': idea.score_audience,
        'total': idea.total_score,
        'name': idea.name
    } for idea in ideas}
    winner = max(ideas, key=lambda idea: idea.total_score, default=None)
    winner_data = {'name': winner.name, 'score': winner.total_score} if winner else None
    socketio.emit('update_scores', {'scores': scores, 'winner': winner_data})

# ================= Run App =================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True, port=5000)
