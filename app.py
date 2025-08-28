import pymysql
pymysql.install_as_MySQLdb()

from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy

import random
import string
import win32com.client
import time
import pythoncom
from datetime import datetime, timedelta
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
from os import getenv
from flask_mail import Mail, Message


app = Flask(__name__)
app.secret_key = 'hello123'  # Use a strong secret key in production

# Enable Flask-SocketIO with CORS to allow mobile access
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuring SQLAlchemy with MYSQL database
DATABASE_URL = getenv('DATABASE_URL', 'mysql+pymysql://root:11111@127.0.0.1/voting_db')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initializing the database
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'home'


# Model for User (email and role)
class User(UserMixin, db.Model):  # Inherit from UserMixin
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(50), nullable=False)

# Model for Idea (name, scores from judge and audience)
class Idea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    score_judge = db.Column(db.Integer, default=0)
    score_audience = db.Column(db.Integer, default=0)
    total_score = db.Column(db.Integer, default=0)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# OTP storage (simulated DB with an array)
otp_storage = {}

# Helper function to generate OTP
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))  # Generates a 6-digit OTP

# Function to send OTP email using Outlook
def send_mail(email, subject, message):
    try:
        # Initialize COM before creating an Outlook application instance
        pythoncom.CoInitialize()
        
        # Create an instance of Outlook
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail_item = outlook.CreateItem(0)  # 0: MailItem

        # Set the properties of the email
        mail_item.Subject = subject
        mail_item.Body = message
        mail_item.To = email

        # Save the message to Sent Items (debugging step)
        mail_item.Save()

        # Force sending the email
        mail_item.Send()

        print("Email sent successfully")

    except Exception as e:
        print(f"Error sending email: {e}")

# Helper function to calculate total scores
def calculate_total_scores():
    ideas = Idea.query.all()  # Fetch all ideas from the database
    for idea in ideas:
        idea.total_score = idea.score_judge + idea.score_audience
    db.session.commit()  # Commit changes to the database

# Helper function to check if OTP is expired
def is_otp_expired(stored_otp):
    if not stored_otp or 'expiry_time' not in stored_otp:
        return True  # Consider missing OTP as expired
    return time.time() > stored_otp['expiry_time']


# Home/Login Page
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        email = request.form['email']
        role = request.form['role']
        user = User.query.filter_by(email=email, role=role).first()
        if user:
            login_user(user)
            session.permanent = True  # Keep user logged in
            return redirect(url_for(f'{role}_dashboard'))
        flash("Invalid email or role.", "danger")
    return render_template('login.html')

# Route for sending OTP
@app.route('/send_otp', methods=['POST'])
def send_otp():
    email = request.form['email']
    role = request.form['role']

    # Restrict email to @amdocs.com only
    if not email.endswith('@amdocs.com'):
        flash("Only @amdocs.com email addresses are allowed!", "danger")
        return redirect(url_for('home'))
    
    user = User.query.filter_by(email=email).first()
    
    if role in ["judge", "admin"]:  # Judges and Admins must be registered
        if not user:
            flash("Email not registered!", "danger")
            return redirect(url_for('home'))
        if user.role != role:
            flash("Role mismatch. Please choose the correct role.", "danger")
            return redirect(url_for('home'))
    
    # Allow anyone to log in as audience
    if role == "audience" and not user:
        user = User(email=email, role=role)
        db.session.add(user)
        db.session.commit()

    # Generate and store OTP
    otp = generate_otp()
    expiry_time = time.time() + 900  # 15 minutes from now
    otp_storage[email] = {"otp": otp, "expiry_time": expiry_time}

    # Send OTP via email
    subject = "Your OTP Code"
    message = f"Your OTP code is: {otp}"
    send_mail(email, subject, message)

    flash(f"OTP sent to {email}. Please check your email.", "success")
    
    # **RETURN STATEMENT ADDED**
    return redirect(url_for('otp_verification', email=email))

 
# Route for OTP verification (Fix: Proper redirection based on role)
@app.route('/otp_verification', methods=['GET', 'POST'])
def otp_verification():
    email = request.args.get('email')  # Get email from query string
    print(f"Email from request: {email}")  # Debugging  

    if request.method == 'POST':
        entered_otp = request.form['otp']
        print(f"Entered OTP: {entered_otp}")  # Debugging
    
        # Retrieve the OTP dictionary entry
        stored_otp = otp_storage.get(email, None)
        print(f"Stored OTP for {email}: {stored_otp}")  # Debugging  

        if not stored_otp:
            flash("No OTP found for this email. Please request a new one.", "danger")
            return redirect(url_for('home'))

        # Check if OTP is expired
        if is_otp_expired(stored_otp):
            flash("OTP has expired. Please request a new one.", "danger")
            del otp_storage[email]  # Remove expired OTP
            return redirect(url_for('home'))

        # Check if entered OTP matches stored OTP
        if entered_otp == stored_otp['otp']:
            del otp_storage[email]  # Delete OTP after successful verification
            print(f"OTP verification successful for {email}")  # Debugging  

            user = User.query.filter_by(email=email).first()

            if user:
                session['role'] = user.role  # Store role in session
                session['user'] = email  #Store email in session
                session.permanent = True  #  Keep session alive
                login_user(user)  #  Ensures user stays logged in

                print(f"User {email} logged in with role {user.role}")  # Debugging
                return redirect(url_for(f'{user.role}_dashboard'))  #  Correct redirection
            else:
                flash("User not found. Please try again.", "danger")
                return redirect(url_for('home'))
        else:
            flash("Invalid OTP. Please try again.", "danger")
            print("Invalid OTP entered!")  # Debugging  
            return redirect(url_for('otp_verification', email=email))

    return render_template('otp_verification.html', email=email)


# Fix in Login Route (Ensuring Users are Stored Correctly)
@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    role = request.form['role']
      # Ensure only @amdocs.com emails can log in
    if not email.endswith('@amdocs.com'):
        flash("Only @amdocs.com email addresses are allowed!", "danger")
        return redirect(url_for('home'))
    
    user = User.query.filter_by(email=email, role=role).first()

    if not user:
        user = User(email=email, role=role)
        db.session.add(user)
        db.session.commit()  # Commit new user

    if user:
        login_user(user)
        session.permanent = True  # Keep session active
        session['role'] = user.role  # Store role
        session['user'] = email  # Store email
        return redirect(url_for(f'{role}_dashboard'))  
    else:
        flash("Invalid email or role!", "danger")
        return redirect(url_for('home'))





# Judge Dashboard
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
        return redirect(url_for('thankyou'))  # Redirect after voting
    return render_template('judge_dashboard.html', ideas=Idea.query.all())

# Audience Dashboard
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
        return redirect(url_for('thankyou'))  # Redirect after voting
    return render_template('audience_dashboard.html', ideas=Idea.query.all())


# Real-time Score Update Function
def update_scores():
    ideas = Idea.query.all()

    # Create scores dictionary
    scores = {idea.id: {
        'judge': idea.score_judge,
        'audience': idea.score_audience,
        'total': idea.total_score,
        'name': idea.name
    } for idea in ideas}

    # Find the idea with the highest total score (Winner)
    winner = max(ideas, key=lambda idea: idea.total_score, default=None)
    winner_data = {'name': winner.name, 'score': winner.total_score} if winner else None

    # Emit updated scores AND the winner to all connected clients
    socketio.emit('update_scores', {'scores': scores, 'winner': winner_data})


# Admin Dashboard
@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('home'))

    ideas = Idea.query.all()

    # Find the idea with the highest total_score
    winner = max(ideas, key=lambda idea: idea.total_score, default=None)

    return render_template('admin_dashboard.html', ideas=ideas, winner=winner)

# Route for result page
@app.route('/result')
def result():
    calculate_total_scores()  # Update total scores for each idea
    return render_template('result.html', total_scores=Idea.query.all())

# Route for Thank You page
@app.route('/thank_you')
def thank_you():
    return render_template('thank_you.html')



# Logout
@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))


# Event to Update Scores
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

    # Call update_scores() to emit updated scores and winner in real time
    update_scores()



if __name__ == '__main__':
    # Create tables before starting the app
    with app.app_context():
        db.create_all()  # Create database tables
    #app.run(debug=True)
    socketio.run(app, debug=True, port=5000)

