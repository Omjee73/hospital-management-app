from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date, time
import os
from models import db, User, Department, Doctor, Patient, Appointment, Treatment, DoctorAvailability
from celery import Celery
import redis
import pathlib

 # Load .env if present (try multiple locations)
def _load_env_from_file(env_path: str | None = None):
    try:
        candidates = []
        if env_path:
            candidates.append(pathlib.Path(env_path))
        here = pathlib.Path(__file__).resolve().parent
        candidates.append(here / '.env')
        candidates.append(here.parent / '.env')
        candidates.append(pathlib.Path.cwd() / '.env')
        seen = set()
        uniq = []
        for p in candidates:
            p = p.resolve()
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        chosen = None
        for p in uniq:
            if p.is_file():
                chosen = p
                break
        if not chosen:
            print('[ENV] .env not found at any of:', [str(p) for p in uniq])
            return
        set_keys = []
        for raw in chosen.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and (key not in os.environ or not os.environ.get(key)):
                os.environ[key] = val
                set_keys.append(key)
        print('[ENV] Loaded .env from', str(chosen))
        if set_keys:
            print('[ENV] New keys set:', ','.join(set_keys))
    except Exception as e:
        print('[ENV] Failed to load .env:', e)

_load_env_from_file()

app = Flask(__name__, template_folder='templates', static_folder='../frontend/static')
app.config['SECRET_KEY'] = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hospital.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

db.init_app(app)

# Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

@login_manager.unauthorized_handler
def handle_unauthorized():
    try:
        if request.path.startswith('/api/') or request.is_json:
            return jsonify({'message': 'Authentication required'}), 401
    except Exception:
        pass
    return redirect(url_for('login'))


# Flask-Login handles unauthorized via handler above

# Use short timeouts so API calls don't hang if Redis is unavailable
redis_client = redis.Redis(
    host='localhost', port=6379, db=1, decode_responses=True,
    socket_timeout=0.3, socket_connect_timeout=0.3
)

celery = Celery(
    app.name,
    broker=app.config['CELERY_BROKER_URL'],
    backend=app.config['CELERY_RESULT_BACKEND']
)
celery.conf.update(app.config)

def cache_get(key):
    try:
        return redis_client.get(key)
    except:
        return None

def cache_set(key, value, expiry=300):
    try:
        redis_client.setex(key, expiry, value)
    except:
        pass

def init_db():
    with app.app_context():
        db.create_all()
        # Lightweight migration: ensure users.is_active column exists (SQLite)
        try:
            from sqlalchemy import text
            res = db.session.execute(text("PRAGMA table_info(users)"))
            cols = [row[1] for row in res]
            if 'is_active' not in cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                db.session.commit()
            # ensure doctor_availability.duration_minutes exists
            res_av = db.session.execute(text("PRAGMA table_info(doctor_availability)"))
            av_cols = [row[1] for row in res_av]
            if 'duration_minutes' not in av_cols:
                db.session.execute(text("ALTER TABLE doctor_availability ADD COLUMN duration_minutes INTEGER DEFAULT 30"))
                db.session.commit()
            if 'custom_times' not in av_cols:
                db.session.execute(text("ALTER TABLE doctor_availability ADD COLUMN custom_times TEXT"))
                db.session.commit()
            # ensure doctors.fee exists
            res_doc = db.session.execute(text("PRAGMA table_info(doctors)"))
            doc_cols = [row[1] for row in res_doc]
            if 'fee' not in doc_cols:
                db.session.execute(text("ALTER TABLE doctors ADD COLUMN fee INTEGER DEFAULT 0"))
                db.session.commit()
            # ensure unique index to prevent double-booking of same doctor/date/time when active
            try:
                idx_list = db.session.execute(text("PRAGMA index_list(appointments)")).fetchall()
                idx_names = [row[1] for row in idx_list]
                if 'uq_doctor_slot_active' not in idx_names:
                    # partial unique index for statuses Booked/Completed
                    db.session.execute(text("""
                        CREATE UNIQUE INDEX IF NOT EXISTS uq_doctor_slot_active
                        ON appointments(doctor_id, date, time)
                        WHERE status IN ('Booked','Completed')
                    """))
                    db.session.commit()
            except Exception as e:
                print('[init_db] unique index creation skipped:', e)
        except Exception as e:
            # Do not block app startup if migration check fails
            print("[init_db] migration check failed:", e)
        
        if not Department.query.first():
            departments = [
                Department(name='Cardiology', description='Heart and cardiovascular system'),
                Department(name='Neurology', description='Brain and nervous system'),
                Department(name='Orthopedics', description='Bones and muscles'),
                Department(name='Pediatrics', description='Children health'),
                Department(name='Dermatology', description='Skin conditions'),
                Department(name='General Medicine', description='General health issues')
            ]
            db.session.add_all(departments)
            db.session.commit()
        
        if not User.query.filter_by(role='admin').first():
            admin_user = User(
                email='admin@hospital.com',
                password=generate_password_hash('admin123'),
                role='admin',
                name='Hospital Administrator',
                contact='9999999999'
            )
            db.session.add(admin_user)
            db.session.commit()
            print("Admin user created: admin@hospital.com / admin123")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    data = request.get_json() or {}
    email = data.get('email')
    password = data.get('password')
    
    user = User.query.filter_by(email=email).first()
    
    if user and check_password_hash(user.password, password):
        # Block login if user is deactivated
        try:
            if hasattr(user, 'is_active') and not user.is_active:
                return jsonify({'message': 'Account is blocked. Contact administrator.'}), 403
        except Exception:
            pass
        login_user(user, remember=False)
        session.permanent = True
        return jsonify({'message': 'Login successful', 'role': user.role}), 200
    
    return jsonify({'message': 'Invalid credentials'}), 401

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    
    data = request.get_json()
    
    if User.query.filter_by(email=data.get('email')).first():
        return jsonify({'message': 'Email already exists'}), 400
    
    user = User(
        email=data.get('email'),
        password=generate_password_hash(data.get('password')),
        role='patient',
        name=data.get('name'),
        contact=data.get('contact')
    )
    db.session.add(user)
    db.session.commit()
    
    patient = Patient(
        user_id=user.id,
        date_of_birth=datetime.strptime(data.get('date_of_birth'), '%Y-%m-%d').date() if data.get('date_of_birth') else None,
        gender=data.get('gender'),
        address=data.get('address'),
        blood_group=data.get('blood_group'),
        emergency_contact=data.get('emergency_contact')
    )
    db.session.add(patient)
    db.session.commit()
    
    return jsonify({'message': 'Registration successful'}), 201

from routes.admin_routes import admin_bp
from routes.doctor_routes import doctor_bp
from routes.patient_routes import patient_bp

app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(doctor_bp, url_prefix='/doctor')
app.register_blueprint(patient_bp, url_prefix='/patient')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
