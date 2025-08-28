import pymysql
pymysql.install_as_MySQLdb()

from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy

import random
import string
import time
from datetime import datetime
from flask_socketio import SocketIO
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
from os import getenv

app = Flask(__name__)
app.secret_key = 'hello123'  # ⚠️ Use a strong key in production

# Enable Flask-SocketIO with CORS to allow mobile/web access
socketio = SocketIO(app, cors_allowed_origins="*")

# Database config (change root:11111 and db name accordingly)
DATABASE_URL = getenv('DATABASE_URL', 'mysql+pymysql://root:11111@127.0.0.1/voting_db')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Login manager setup
login_manager = LoginManager(app)
login_manager.login_view = 'home'

# -------------------- MODELS --------------------
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

# -------------------- OTP HANDLING --------------------
otp_storage = {}

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_mail_console(email, subject, message):
    """Instead of sending mail, print OTP in console/logs (for demo/POC)."""
    print(f"\n============================")
    print(f"📧 OTP for {email}")
    print(f"Subject: {subject}")
    print(f"Message: {message}")
    print(f"============================\n")

def is_otp_expired(stored_otp):
    if not stored_otp or 'expiry_time' not in stored_otp:
        return True
    return time.time() > stored_otp['expiry_time']

# -------------------- ROUTES --------------------
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

    if not email.endswith('@amdocs.com'):
        flash("Only @amdocs.com email addresses are allowed!", "danger")
        return redirect(url_for('home'))

    user = User.query.filter_by(email=email).first()

    if role in ["judge", "admin"]:
        if not user:
            flash("Email not registered!", "danger")
            return redirect(url_for('home'))
        if user.role != role:
            flash("Role mismatch.", "danger")
            return redirect(url_for('home'))

    if role == "audience" and not user:
        user = User(email=email, role=role)
        db.session.add(user)
        db.session.commit()

    otp = generate_otp()
    expiry_time = time.time() + 900
    otp_storage[email] = {"otp": otp, "expiry_time": expiry_time}

    # 🔑 Instead of real email, log OTP in console
    subject = "Your OTP Code"
    message = f"Your OTP code is: {otp}"
    send_mail_console(email, subject, message)

    flash(f"OTP generated for {email}. Check console logs!", "success")
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
            flash("OTP expired.", "danger")
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
            flash("Invalid OTP.", "danger")
            return redirect(url_for('otp_verification', email=email))

    return render_template('otp_verification.html', email=email)

# -------------------- DASHBOARDS --------------------
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
        return redirect(url_for('thank_you'))
    return render_template('audience_dashboard.html', ideas=Idea.query.all())

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('home'))
    ideas = Idea.query.all()
    winner = max(ideas, key=lambda i: i.total_score, default=None)
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

# -------------------- SOCKET.IO EVENTS --------------------
@socketio.on('submit_scores')
def handle_score_submission(data):
    for idea_id, score in data.items():
        idea = Idea.query.get(int(idea_id))
        if idea:
            if current_user.role == 'judge':
                idea.score_judge += int(score)
            elif current_user.role == 'audience':
                idea.score_audience += int(score)
            idea.total_score = idea.score_judge + idea.score_audience
        db.session.commit()
    # Emit real-time score update
    socketio.emit('update_scores', {i.id: i.total_score for i in Idea.query.all()})

# -------------------- MAIN --------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True, port=5000)
