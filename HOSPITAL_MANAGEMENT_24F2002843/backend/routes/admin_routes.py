from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from models import db, User, Doctor, Patient, Department, Appointment, DoctorAvailability
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy.orm import joinedload

admin_bp = Blueprint('admin', __name__)

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return jsonify({'message': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    return wrapper

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    # Provide initial stats to the Jinja template to avoid undefined errors.
    doctors_count = Doctor.query.filter_by(is_active=True).count()
    patients_count = Patient.query.count()
    appointments_count = Appointment.query.filter_by(status='Booked').count()
    stats = {
        'doctors': doctors_count,
        'patients': patients_count,
        'appointments': appointments_count
    }
    return render_template('admin/dashboard.html', stats=stats)

@admin_bp.route('/stats')
@admin_required
def get_stats():
    doctors_count = Doctor.query.filter_by(is_active=True).count()
    patients_count = Patient.query.count()
    appointments_count = Appointment.query.filter_by(status='Booked').count()
    total_appointments = Appointment.query.count()
    
    return jsonify({
        'doctors': doctors_count,
        'patients': patients_count,
        'appointments': appointments_count,
        'total_appointments': total_appointments
    })

@admin_bp.route('/stats/charts')
@admin_required
def get_chart_stats():
    """Return datasets for charts on admin dashboard.
    - Monthly appointments for last 6 months (all statuses)
    - Pie of appointments by status overall
    """
    from sqlalchemy import extract
    today = datetime.utcnow()
    # last 6 months including current
    labels = []
    series = []
    base = datetime(today.year, today.month, 1)
    for i in range(5, -1, -1):
        m = (base.month - i - 1) % 12 + 1
        y = base.year + ((base.month - i - 1) // 12)
        labels.append(f"{y}-{m:02d}")
        count = Appointment.query.filter(
            extract('year', Appointment.date) == y,
            extract('month', Appointment.date) == m
        ).count()
        series.append(count)
    # status distribution
    statuses = ['Booked', 'Completed', 'Cancelled']
    status_counts = [Appointment.query.filter_by(status=s).count() for s in statuses]
    return jsonify({
        'monthly': { 'labels': labels, 'data': series },
        'statusDist': { 'labels': statuses, 'data': status_counts }
    })

@admin_bp.route('/doctors')
@admin_required
def doctors_page():
    return render_template('admin/doctors.html')

@admin_bp.route('/api/doctors', methods=['GET'])
@admin_required
def get_doctors():
    import json
    from app import redis_client
    
    cache_key = 'admin:doctors:all'
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except:
        pass
    
    # Eager load related user and department to avoid N+1 queries
    doctors = Doctor.query.options(
        joinedload(Doctor.user),
        joinedload(Doctor.department)
    ).all()
    result = [doctor.to_dict() for doctor in doctors]
    
    try:
        redis_client.setex(cache_key, 300, json.dumps(result))
    except:
        pass
    
    return jsonify(result)

@admin_bp.route('/api/doctors', methods=['POST'])
@admin_required
def add_doctor():
    from app import redis_client
    data = request.get_json()

    required_fields = ['email', 'password', 'name', 'contact', 'department_id', 'specialization', 'experience', 'qualification', 'fee']
    # Treat empty strings as missing; allow 0 for numeric fields like experience
    missing = []
    for f in required_fields:
        v = data.get(f)
        if isinstance(v, str):
            v = v.strip()
            data[f] = v
        if (v is None or v == '') and v != 0:
            missing.append(f)
    if missing:
        return jsonify({'message': 'Missing required fields', 'missing': missing}), 400
    # Simple format validations (lightweight)
    if '@' not in data.get('email'):
        return jsonify({'message': 'Invalid email format'}), 400
    try:
        exp_val = int(data.get('experience'))
        if exp_val < 0:
            return jsonify({'message': 'Experience must be non-negative'}), 400
    except Exception:
        return jsonify({'message': 'Experience must be an integer'}), 400
    # Fee validation (non-negative integer)
    try:
        fee_val = int(data.get('fee'))
        if fee_val < 0:
            return jsonify({'message': 'Fee must be non-negative'}), 400
    except Exception:
        return jsonify({'message': 'Fee must be an integer'}), 400
    
    if User.query.filter_by(email=data.get('email')).first():
        return jsonify({'message': 'Email already exists'}), 400
    
    user = User(
        email=data.get('email'),
        # Do not fallback; password is mandatory and already validated above
        password=generate_password_hash(data.get('password')),
        role='doctor',
        name=data.get('name'),
        contact=data.get('contact')
    )
    db.session.add(user)
    db.session.commit()
    
    doctor = Doctor(
        user_id=user.id,
        department_id=data.get('department_id'),
        specialization=data.get('specialization'),
        experience=int(data.get('experience')),
        qualification=data.get('qualification'),
        fee=int(data.get('fee')),
        is_active=True
    )
    db.session.add(doctor)
    db.session.commit()
    
    try:
        redis_client.delete('admin:doctors:all')
    except:
        pass
    
    return jsonify({'message': 'Doctor added successfully', 'doctor': doctor.to_dict()}), 201

@admin_bp.route('/api/doctors/<int:doctor_id>', methods=['PUT'])
@admin_required
def update_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    data = request.get_json()
    
    doctor.user.name = data.get('name', doctor.user.name)
    doctor.user.contact = data.get('contact', doctor.user.contact)
    # Optional password reset
    new_password = data.get('password')
    if new_password:
        from werkzeug.security import generate_password_hash
        doctor.user.password = generate_password_hash(new_password)
    doctor.department_id = data.get('department_id', doctor.department_id)
    doctor.specialization = data.get('specialization', doctor.specialization)
    doctor.experience = data.get('experience', doctor.experience)
    doctor.qualification = data.get('qualification', doctor.qualification)
    if 'fee' in data and data.get('fee') is not None:
        try:
            doctor.fee = int(data.get('fee'))
        except Exception:
            pass
    
    db.session.commit()
    # Invalidate cached list so UI sees the updated doctor immediately
    try:
        from app import redis_client
        redis_client.delete('admin:doctors:all')
    except Exception:
        pass

    return jsonify({'message': 'Doctor updated successfully', 'doctor': doctor.to_dict()})

@admin_bp.route('/api/doctors/<int:doctor_id>', methods=['DELETE'])
@admin_required
def delete_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    doctor.is_active = False
    db.session.commit()
    # Invalidate cached list so UI sees the deactivated doctor immediately
    try:
        from app import redis_client
        redis_client.delete('admin:doctors:all')
    except Exception:
        pass

    return jsonify({'message': 'Doctor deactivated successfully'})


@admin_bp.route('/api/doctors/<int:doctor_id>/activate', methods=['POST'])
@admin_required
def activate_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    doctor.is_active = True
    db.session.commit()
    # Invalidate cache so UI sees the updated status
    try:
        from app import redis_client
        redis_client.delete('admin:doctors:all')
    except Exception:
        pass
    return jsonify({'message': 'Doctor activated successfully', 'doctor': doctor.to_dict()})

@admin_bp.route('/patients')
@admin_required
def patients_page():
    return render_template('admin/patients.html')

@admin_bp.route('/api/patients', methods=['GET'])
@admin_required
def get_patients():
    # Eager load related user to avoid N+1 queries
    patients = Patient.query.options(
        joinedload(Patient.user)
    ).all()
    return jsonify([patient.to_dict() for patient in patients])

@admin_bp.route('/api/patients/<int:patient_id>', methods=['GET'])
@admin_required
def get_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    return jsonify(patient.to_dict())

@admin_bp.route('/api/patients/<int:patient_id>/history', methods=['GET'])
@admin_required
def get_patient_history(patient_id):
    """Return all appointments for a given patient (for admin view)."""
    appointments = (Appointment.query.options(
        joinedload(Appointment.patient).joinedload(Patient.user),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.treatment)
    ).filter(
        Appointment.patient_id == patient_id
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all())
    return jsonify([apt.to_dict() for apt in appointments])

@admin_bp.route('/api/patients/<int:patient_id>', methods=['PUT'])
@admin_required
def update_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    data = request.get_json()
    
    patient.user.name = data.get('name', patient.user.name)
    patient.user.contact = data.get('contact', patient.user.contact)
    patient.address = data.get('address', patient.address)
    patient.blood_group = data.get('blood_group', patient.blood_group)
    patient.emergency_contact = data.get('emergency_contact', patient.emergency_contact)
    
    db.session.commit()
    
    return jsonify({'message': 'Patient updated successfully', 'patient': patient.to_dict()})

@admin_bp.route('/api/patients/<int:patient_id>/block', methods=['POST'])
@admin_required
def block_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    patient.user.is_active = False
    db.session.commit()
    return jsonify({'message': 'Patient blocked successfully', 'patient': patient.to_dict()})

@admin_bp.route('/api/patients/<int:patient_id>/activate', methods=['POST'])
@admin_required
def activate_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    patient.user.is_active = True
    db.session.commit()
    return jsonify({'message': 'Patient activated successfully', 'patient': patient.to_dict()})

@admin_bp.route('/appointments')
@admin_required
def appointments_page():
    return render_template('admin/appointments.html')

@admin_bp.route('/api/appointments', methods=['GET'])
@admin_required
def get_appointments():
    # Eager load patient->user, doctor->user, and treatment to avoid N+1 queries
    appointments = (Appointment.query.options(
        joinedload(Appointment.patient).joinedload(Patient.user),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.treatment)
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all())
    return jsonify([apt.to_dict() for apt in appointments])

@admin_bp.route('/api/departments', methods=['GET'])
@admin_required
def get_departments():
    departments = Department.query.all()
    return jsonify([dept.to_dict() for dept in departments])

@admin_bp.route('/search/doctors', methods=['GET'])
@admin_required
def search_doctors():
    query = request.args.get('q', '').lower()
    # Join for filtering; eager load relationships for serialization
    doctors = Doctor.query.join(User).options(
        joinedload(Doctor.user),
        joinedload(Doctor.department)
    ).filter(
        db.or_(
            User.name.ilike(f'%{query}%'),
            Doctor.specialization.ilike(f'%{query}%')
        )
    ).all()
    
    return jsonify([doctor.to_dict() for doctor in doctors])

@admin_bp.route('/search/patients', methods=['GET'])
@admin_required
def search_patients():
    query = request.args.get('q', '').lower()
    # Join for filtering; eager load user for serialization
    patients = Patient.query.join(User).options(
        joinedload(Patient.user)
    ).filter(
        db.or_(
            User.name.ilike(f'%{query}%'),
            User.contact.ilike(f'%{query}%'),
            Patient.id == int(query) if query.isdigit() else False
        )
    ).all()
    
    return jsonify([patient.to_dict() for patient in patients])

@admin_bp.route('/profile')
@admin_required
def profile():
    # Provide the current user's data to the template for initial state
    profile_data = {}
    try:
        if current_user.is_authenticated:
            profile_data = current_user.to_dict()
    except Exception:
        profile_data = {}

    return render_template('admin/profile.html', profile_data=profile_data)

@admin_bp.route('/api/profile', methods=['GET'])
@admin_required
def get_profile():
    if not current_user.is_authenticated:
        return jsonify({'message': 'Authentication required'}), 401
    return jsonify(current_user.to_dict())

@admin_bp.route('/api/profile', methods=['PUT'])
@admin_required
def update_profile():
    if not current_user.is_authenticated:
        return jsonify({'message': 'Authentication required'}), 401
    user = User.query.get_or_404(current_user.id)
    data = request.get_json()
    
    user.name = data.get('name', user.name)
    user.contact = data.get('contact', user.contact)
    
    if data.get('password'):
        user.password = generate_password_hash(data.get('password'))
    
    db.session.commit()
    
    return jsonify({'message': 'Profile updated successfully', 'user': user.to_dict()})
