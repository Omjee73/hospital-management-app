from flask import Blueprint, render_template, request, jsonify, send_from_directory, current_app, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from models import db, User, Doctor, Patient, Appointment, Treatment, DoctorAvailability, Department
from datetime import datetime, date, timedelta
from functools import wraps
import csv
import io
from sqlalchemy.orm import joinedload
import json
import os
import re
# Removed ReportLab-based PDF generation to comply with allowed frameworks

patient_bp = Blueprint('patient', __name__)

def patient_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'patient':
            return jsonify({'message': 'Patient access required'}), 403
        return fn(*args, **kwargs)
    return wrapper

@patient_bp.route('/dashboard')
@patient_required
def dashboard():
    return render_template('patient/dashboard.html')

@patient_bp.route('/stats')
@patient_required
def get_stats():
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    
    upcoming = Appointment.query.filter(
        Appointment.patient_id == patient.id,
        Appointment.date >= date.today(),
        Appointment.status == 'Booked'
    ).count()
    
    completed = Appointment.query.filter(
        Appointment.patient_id == patient.id,
        Appointment.status == 'Completed'
    ).count()
    
    cancelled = Appointment.query.filter(
        Appointment.patient_id == patient.id,
        Appointment.status == 'Cancelled'
    ).count()
    
    return jsonify({
        'upcoming': upcoming,
        'completed': completed,
        'cancelled': cancelled
    })

@patient_bp.route('/appointments')
@patient_required
def appointments_page():
    return render_template('patient/appointments.html')

@patient_bp.route('/api/appointments', methods=['GET'])
@patient_required
def get_appointments():
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    
    appointments = (Appointment.query.options(
        joinedload(Appointment.patient).joinedload(Patient.user),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.treatment)
    ).filter_by(
        patient_id=patient.id
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all())
    
    return jsonify([apt.to_dict() for apt in appointments])

@patient_bp.route('/book-appointment')
@patient_required
def book_appointment_page():
    return render_template('patient/book_appointment.html')

@patient_bp.route('/api/doctors', methods=['GET'])
@patient_required
def get_doctors():
    # Cache list of active doctors for 5 minutes
    cache_key = 'patient:doctors:all'
    try:
        from app import redis_client
        cached = redis_client.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except Exception:
        pass
    doctors = Doctor.query.options(
        joinedload(Doctor.user),
        joinedload(Doctor.department)
    ).filter_by(is_active=True).all()
    payload = [doctor.to_dict() for doctor in doctors]
    try:
        redis_client.setex(cache_key, 300, json.dumps(payload))
    except Exception:
        pass
    return jsonify(payload)

@patient_bp.route('/api/departments', methods=['GET'])
@patient_required
def get_departments_with_doctors():
    """Return all departments with general info and active doctors in each category.
    Includes computed stats like doctor_count and avg_fee.
    """
    # Cache departments payload for 5 minutes
    cache_key = 'patient:departments'
    try:
        from app import redis_client
        cached = redis_client.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except Exception:
        pass
    departments = Department.query.all()
    result = []
    for dept in departments:
        active_doctors = [d for d in dept.doctors if getattr(d, 'is_active', True)]
        # compose doctor profiles
        doctors_payload = []
        fees = []
        for d in active_doctors:
            try:
                fees.append(int(getattr(d, 'fee', 0) or 0))
            except Exception:
                pass
            doctors_payload.append({
                'id': d.id,
                'name': getattr(d.user, 'name', ''),
                'email': getattr(d.user, 'email', ''),
                'contact': getattr(d.user, 'contact', ''),
                'specialization': d.specialization,
                'experience': d.experience,
                'qualification': d.qualification,
                'fee': getattr(d, 'fee', 0),
                'is_active': d.is_active
            })
        avg_fee = int(sum(fees) / len(fees)) if fees else 0
        result.append({
            'id': dept.id,
            'name': dept.name,
            'description': dept.description,
            'doctor_count': len(active_doctors),
            'avg_fee': avg_fee,
            'doctors': doctors_payload
        })
    # Sort by department name for stable UI
    result.sort(key=lambda x: (x['name'] or '').lower())
    try:
        from app import redis_client
        redis_client.setex(cache_key, 300, json.dumps(result))
    except Exception:
        pass
    return jsonify(result)

@patient_bp.route('/api/doctors/<int:doctor_id>/availability', methods=['GET'])
@patient_required
def get_doctor_availability(doctor_id):
    today = date.today()
    # Short cache (15s) to smooth repeated fetches
    cache_key = f'patient:doctor:{doctor_id}:availability'
    try:
        from app import redis_client
        cached = redis_client.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except Exception:
        pass
    availability = DoctorAvailability.query.filter(
        DoctorAvailability.doctor_id == doctor_id,
        DoctorAvailability.date >= today,
        DoctorAvailability.is_available == True
    ).order_by(DoctorAvailability.date).all()
    payload = [av.to_dict() for av in availability]
    try:
        from app import redis_client
        redis_client.setex(cache_key, 15, json.dumps(payload))
    except Exception:
        pass
    return jsonify(payload)

@patient_bp.route('/api/doctors/<int:doctor_id>/slots', methods=['GET'])
@patient_required
def get_doctor_slots(doctor_id):
    """Return time slots derived from availability for a given date.
    Query params: date=YYYY-MM-DD (required)
    """
    q_date = request.args.get('date')
    if not q_date:
        return jsonify({'message': 'date is required'}), 400
    try:
        target_date = datetime.strptime(q_date, '%Y-%m-%d').date()
    except Exception:
        return jsonify({'message': 'invalid date'}), 400
    # Try cache first (15s)
    cache_key = f'patient:doctor:{doctor_id}:slots:{target_date.isoformat()}'
    try:
        from app import redis_client
        cached = redis_client.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except Exception:
        pass
    
    av = DoctorAvailability.query.filter_by(
        doctor_id=doctor_id,
        date=target_date,
        is_available=True
    ).first()
    if not av:
        return jsonify({'date': target_date.isoformat(), 'slots': []})
    
    # Build set of booked times for this doctor/date
    booked_times = set(
        a.time.strftime('%H:%M') for a in Appointment.query.filter_by(
            doctor_id=doctor_id,
            date=target_date
        ).all()
        if a.status in ('Booked', 'Completed')
    )
    
    # Generate slots between start and end using duration
    duration = av.duration_minutes or 30
    start_dt = datetime.combine(target_date, av.start_time)
    end_dt = datetime.combine(target_date, av.end_time)
    slots = []
    cur = start_dt
    while cur < end_dt:
        label = cur.strftime('%H:%M')
        slots.append({
            'time': label,
            'available': label not in booked_times
        })
        cur = cur + timedelta(minutes=duration)

    # cache slots very briefly (15s)
    try:
        from app import redis_client
        redis_client.setex(cache_key, 15, json.dumps({'date': target_date.isoformat(), 'slots': slots}))
    except Exception:
        pass
    return jsonify({'date': target_date.isoformat(), 'slots': slots})

@patient_bp.route('/api/appointments', methods=['POST'])
@patient_required
def book_appointment():
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    
    data = request.get_json()
    # Parse inputs
    try:
        doctor_id = int(data.get('doctor_id'))
        appt_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
        appt_time = datetime.strptime(data.get('time'), '%H:%M').time()
    except Exception:
        return jsonify({'message': 'Invalid input'}), 400

    # Prevent duplicate slot booking for same doctor/date/time if Booked/Completed exists
    existing = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date == appt_date,
        Appointment.time == appt_time,
        Appointment.status.in_(['Booked', 'Completed'])
    ).first()
    if existing:
        return jsonify({'message': 'Selected slot is no longer available. Please pick another time.'}), 409

    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=doctor_id,
        date=appt_date,
        time=appt_time,
        reason=data.get('reason'),
        status='Booked'
    )
    db.session.add(appointment)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Handle rare race conditions guarded by unique index
        return jsonify({'message': 'Selected slot just got booked by someone else. Please choose another slot.'}), 409
    # Invalidate cached slots for this doctor/date
    try:
        from app import redis_client
        redis_client.delete(f'patient:doctor:{doctor_id}:slots:{appt_date.isoformat()}')
    except Exception:
        pass

    return jsonify({'message': 'Appointment booked successfully', 'appointment': appointment.to_dict()}), 201

@patient_bp.route('/api/appointments/<int:appointment_id>', methods=['PUT'])
@patient_required
def reschedule_appointment(appointment_id):
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    
    appointment = Appointment.query.filter_by(
        id=appointment_id,
        patient_id=patient.id
    ).first_or_404()
    
    data = request.get_json()
    
    old_date = appointment.date
    new_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
    new_time = datetime.strptime(data.get('time'), '%H:%M').time()
    # Check conflict for same doctor/date/time excluding this appointment
    conflict = Appointment.query.filter(
        Appointment.doctor_id == appointment.doctor_id,
        Appointment.date == new_date,
        Appointment.time == new_time,
        Appointment.id != appointment.id,
        Appointment.status.in_(['Booked', 'Completed'])
    ).first()
    if conflict:
        return jsonify({'message': 'Selected slot is no longer available. Pick a different time.'}), 409
    appointment.date = new_date
    appointment.time = new_time
    appointment.status = 'Booked'
    
    # Capture old/new for cache invalidation
    db.session.commit()
    try:
        from app import redis_client
        # invalidate both old and new date caches for this doctor
        if old_date:
            redis_client.delete(f'patient:doctor:{appointment.doctor_id}:slots:{old_date.isoformat()}')
        redis_client.delete(f'patient:doctor:{appointment.doctor_id}:slots:{new_date.isoformat()}')
    except Exception:
        pass
    
    return jsonify({'message': 'Appointment rescheduled successfully', 'appointment': appointment.to_dict()})

@patient_bp.route('/api/appointments/<int:appointment_id>', methods=['DELETE'])
@patient_required
def cancel_appointment(appointment_id):
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    
    appointment = Appointment.query.filter_by(
        id=appointment_id,
        patient_id=patient.id
    ).first_or_404()
    
    appointment.status = 'Cancelled'
    db.session.commit()
    # Invalidate slots for that doctor/date as a slot reopened
    try:
        from app import redis_client
        redis_client.delete(f'patient:doctor:{appointment.doctor_id}:slots:{appointment.date.isoformat()}')
    except Exception:
        pass
    
    return jsonify({'message': 'Appointment cancelled successfully'})

@patient_bp.route('/history')
@patient_required
def history_page():
    return render_template('patient/history.html')

@patient_bp.route('/api/history', methods=['GET'])
@patient_required
def get_history():
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    
    appointments = Appointment.query.filter_by(
        patient_id=patient.id,
        status='Completed'
    ).order_by(Appointment.date.desc()).all()
    
    return jsonify([apt.to_dict() for apt in appointments])

@patient_bp.route('/history/print/<int:appointment_id>', methods=['GET'])
@patient_required
def print_history_view(appointment_id):
    patient = Patient.query.filter_by(user_id=current_user.id).first()

    appt = Appointment.query.options(
        joinedload(Appointment.patient).joinedload(Patient.user),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.treatment)
    ).filter_by(id=appointment_id, patient_id=patient.id).first_or_404()

    # Render a simple print-friendly HTML view
    return render_template('patient/history_print.html', appt=appt)

@patient_bp.route('/search/doctors', methods=['GET'])
@patient_required
def search_doctors():
    query = request.args.get('q', '').lower()
    
    doctors = Doctor.query.filter(
        Doctor.is_active == True,
        Doctor.specialization.ilike(f'%{query}%')
    ).all()
    
    return jsonify([doctor.to_dict() for doctor in doctors])

@patient_bp.route('/profile')
@patient_required
def profile():
    # Prefill profile form with server-side data for immediate render
    profile_data = {}
    try:
        user = User.query.get(current_user.id)
        if user:
            profile_data = {
                'id': user.id,
                'name': user.name,
                'email': user.email,
                'contact': user.contact,
                'role': user.role,
            }
            patient = Patient.query.filter_by(user_id=user.id).first()
            if patient:
                profile_data.update({
                    'address': patient.address or '',
                    'blood_group': patient.blood_group or '',
                    'emergency_contact': patient.emergency_contact or '',
                    'date_of_birth': patient.date_of_birth.isoformat() if patient.date_of_birth else ''
                })
    except Exception:
        profile_data = {}

    return render_template('patient/profile.html', profile_data=profile_data)

@patient_bp.route('/api/profile', methods=['GET'])
@patient_required
def get_profile():
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    return jsonify(patient.to_dict())

@patient_bp.route('/api/profile', methods=['PUT'])
@patient_required
def update_profile():
    user = User.query.get_or_404(current_user.id)
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    data = request.get_json()
    
    user.name = data.get('name', user.name)
    user.contact = data.get('contact', user.contact)
    
    if data.get('password'):
        user.password = generate_password_hash(data.get('password'))
    
    patient.address = data.get('address', patient.address)
    patient.blood_group = data.get('blood_group', patient.blood_group)
    patient.emergency_contact = data.get('emergency_contact', patient.emergency_contact)
    
    if data.get('date_of_birth'):
        patient.date_of_birth = datetime.strptime(data.get('date_of_birth'), '%Y-%m-%d').date()
    
    db.session.commit()
    
    return jsonify({'message': 'Profile updated successfully', 'patient': patient.to_dict()})

@patient_bp.route('/api/export-history', methods=['POST'])
@patient_required
def export_history():
    from celery_tasks import export_patient_history_task
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    try:
        task = export_patient_history_task.delay(patient.id)
        return jsonify({'message': 'Export started', 'task_id': task.id})
    except Exception as e:
        # Celery or broker not available
        current_app.logger.exception('Failed to queue export task')
        return jsonify({'message': 'Failed to queue export. Ensure Celery worker and Redis are running.', 'error': str(e)}), 503

@patient_bp.route('/api/exports', methods=['GET'])
@patient_required
def list_exports():
    """Return a list of CSV exports available for the current patient with download URLs."""
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    exports_dir = os.path.join(current_app.root_path, 'exports')
    results = []
    pattern = re.compile(rf'^patient_{patient.id}_history_\d{8}_\d{6}\.csv$')
    try:
        if os.path.isdir(exports_dir):
            for fname in os.listdir(exports_dir):
                if pattern.match(fname):
                    full_path = os.path.join(exports_dir, fname)
                    try:
                        mtime = os.path.getmtime(full_path)
                    except Exception:
                        mtime = 0
                    results.append({'filename': fname, 'mtime': mtime})
        # newest first
        results.sort(key=lambda x: x['mtime'], reverse=True)
        # attach URLs
        for r in results:
            r['url'] = f"/patient/exports/{r['filename']}"
    except Exception:
        results = []
    return jsonify(results)

@patient_bp.route('/exports/<path:filename>', methods=['GET'])
@patient_required
def download_export(filename):
    """Serve a CSV export if it belongs to the current patient and exists."""
    patient = Patient.query.filter_by(user_id=current_user.id).first()
    # very strict allow-list: patient_<id>_history_YYYYMMDD_HHMMSS.csv
    allowed = re.compile(rf'^patient_{patient.id}_history_\d{{8}}_\d{{6}}\.csv$')
    if not allowed.match(filename):
        return abort(403)
    exports_dir = os.path.join(current_app.root_path, 'exports')
    if not os.path.isfile(os.path.join(exports_dir, filename)):
        return abort(404)
    return send_from_directory(exports_dir, filename, as_attachment=True, mimetype='text/csv')

