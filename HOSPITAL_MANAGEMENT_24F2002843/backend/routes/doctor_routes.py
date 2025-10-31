from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from models import db, User, Doctor, Patient, Appointment, Treatment, DoctorAvailability
from datetime import datetime, timedelta, date, time
from functools import wraps
from sqlalchemy.orm import joinedload

doctor_bp = Blueprint('doctor', __name__)

def doctor_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'doctor':
            return jsonify({'message': 'Doctor access required'}), 403
        return fn(*args, **kwargs)
    return wrapper

@doctor_bp.route('/dashboard')
@doctor_required
def dashboard():
    return render_template('doctor/dashboard.html')

@doctor_bp.route('/stats')
@doctor_required
def get_stats():
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    today = date.today()
    upcoming = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date >= today,
        Appointment.status == 'Booked'
    ).count()
    
    total_patients = db.session.query(Appointment.patient_id).filter(
        Appointment.doctor_id == doctor.id
    ).distinct().count()
    
    completed = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.status == 'Completed'
    ).count()
    
    return jsonify({
        'upcoming_appointments': upcoming,
        'total_patients': total_patients,
        'completed_appointments': completed
    })

@doctor_bp.route('/stats/charts')
@doctor_required
def get_chart_stats():
    """Return datasets for charts on doctor dashboard:
    - Monthly appointments for last 6 months for current doctor
    - Status distribution for current doctor
    """
    from sqlalchemy import extract
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    today = date.today()
    labels = []
    series = []
    base_y, base_m = today.year, today.month
    for i in range(5, -1, -1):
        m = (base_m - i - 1) % 12 + 1
        y = base_y + ((base_m - i - 1) // 12)
        labels.append(f"{y}-{m:02d}")
        count = Appointment.query.filter(
            Appointment.doctor_id == doctor.id,
            extract('year', Appointment.date) == y,
            extract('month', Appointment.date) == m
        ).count()
        series.append(count)
    statuses = ['Booked', 'Completed', 'Cancelled']
    status_counts = [Appointment.query.filter_by(doctor_id=doctor.id, status=s).count() for s in statuses]
    return jsonify({
        'monthly': { 'labels': labels, 'data': series },
        'statusDist': { 'labels': statuses, 'data': status_counts }
    })

# Removed standalone appointments page; unified under Treatment

@doctor_bp.route('/api/appointments', methods=['GET'])
@doctor_required
def get_appointments():
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    status = request.args.get('status', 'all')
    
    query = Appointment.query.filter_by(doctor_id=doctor.id)
    
    if status != 'all':
        query = query.filter_by(status=status)
    
    appointments = query.options(
        joinedload(Appointment.patient).joinedload(Patient.user),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.doctor).joinedload(Doctor.department),
        joinedload(Appointment.treatment)
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all()
    return jsonify([apt.to_dict() for apt in appointments])

@doctor_bp.route('/api/appointments/<int:appointment_id>/status', methods=['PUT'])
@doctor_required
def update_appointment_status(appointment_id):
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    appointment = Appointment.query.filter_by(id=appointment_id, doctor_id=doctor.id).first_or_404()
    data = request.get_json()
    
    appointment.status = data.get('status')
    db.session.commit()
    
    return jsonify({'message': 'Appointment status updated', 'appointment': appointment.to_dict()})

@doctor_bp.route('/api/appointments/<int:appointment_id>', methods=['GET'])
@doctor_required
def get_appointment_details(appointment_id):
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()

    appt = Appointment.query.options(
        joinedload(Appointment.patient).joinedload(Patient.user),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.treatment)
    ).filter_by(id=appointment_id, doctor_id=doctor.id).first_or_404()

    data = appt.to_dict()
    try:
        # include department name as location if available
        data['location'] = appt.doctor.department.name if appt.doctor and appt.doctor.department else None
    except Exception:
        data['location'] = None
    return jsonify(data)

@doctor_bp.route('/patients')
@doctor_required
def patients_page():
    return render_template('doctor/patients.html')

@doctor_bp.route('/api/patients', methods=['GET'])
@doctor_required
def get_patients():
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    patient_ids = db.session.query(Appointment.patient_id).filter(
        Appointment.doctor_id == doctor.id
    ).distinct().all()
    
    patients = Patient.query.options(
        joinedload(Patient.user)
    ).filter(Patient.id.in_([p[0] for p in patient_ids])).all()
    return jsonify([patient.to_dict() for patient in patients])

@doctor_bp.route('/api/patients/<int:patient_id>/history', methods=['GET'])
@doctor_required
def get_patient_history(patient_id):
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    appointments = Appointment.query.filter_by(
        patient_id=patient_id,
        doctor_id=doctor.id
    ).order_by(Appointment.date.desc()).all()
    
    return jsonify([apt.to_dict() for apt in appointments])

@doctor_bp.route('/treatment')
@doctor_required
def treatment_page():
    return render_template('doctor/treatment.html')

@doctor_bp.route('/api/treatment', methods=['POST'])
@doctor_required
def add_treatment():
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    data = request.get_json()
    appointment_id = data.get('appointment_id')
    
    appointment = Appointment.query.filter_by(
        id=appointment_id,
        doctor_id=doctor.id
    ).first_or_404()
    
    treatment = Treatment.query.filter_by(appointment_id=appointment_id).first()
    
    if treatment:
        treatment.diagnosis = data.get('diagnosis', treatment.diagnosis)
        treatment.prescription = data.get('prescription', treatment.prescription)
        treatment.notes = data.get('notes', treatment.notes)
        treatment.updated_at = datetime.utcnow()
    else:
        treatment = Treatment(
            appointment_id=appointment_id,
            diagnosis=data.get('diagnosis'),
            prescription=data.get('prescription'),
            notes=data.get('notes')
        )
        db.session.add(treatment)
    # Mark appointment as Completed when treatment is saved/updated
    appointment.status = 'Completed'
    db.session.commit()
    
    # Reload the appointment with relationships for client-side updates
    updated_appointment = Appointment.query.options(
        joinedload(Appointment.patient).joinedload(Patient.user),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.treatment)
    ).get(appointment.id)
    
    return jsonify({
        'message': 'Treatment updated successfully',
        'treatment': treatment.to_dict(),
        'appointment': updated_appointment.to_dict() if updated_appointment else None
    })

@doctor_bp.route('/availability')
@doctor_required
def availability_page():
    return render_template('doctor/availability.html')

@doctor_bp.route('/api/availability', methods=['GET'])
@doctor_required
def get_availability():
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    today = date.today()
    # Return all upcoming availability from today onward (no upper cap)
    availability = DoctorAvailability.query.filter(
        DoctorAvailability.doctor_id == doctor.id,
        DoctorAvailability.date >= today,
        DoctorAvailability.is_available == True
    ).order_by(DoctorAvailability.date).all()
    
    return jsonify([av.to_dict() for av in availability])

@doctor_bp.route('/api/availability', methods=['POST'])
@doctor_required
def set_availability():
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    data = request.get_json()
    
    availability_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
    start_time = datetime.strptime(data.get('start_time'), '%H:%M').time()
    end_time = datetime.strptime(data.get('end_time'), '%H:%M').time()

    # Basic sanity: ensure end after start
    if datetime.combine(availability_date, end_time) <= datetime.combine(availability_date, start_time):
        return jsonify({'message': 'End time must be after start time'}), 400

    duration_val = 30
    try:
        duration_val = int(data.get('duration_minutes') or 30)
    except Exception:
        duration_val = 30

    apply_to_next = bool(data.get('apply_to_next_days', False))

    # Helper to upsert a single date
    def upsert_for_date(dt):
        existing = DoctorAvailability.query.filter_by(
            doctor_id=doctor.id,
            date=dt
        ).first()
        if existing:
            existing.start_time = start_time
            existing.end_time = end_time
            existing.is_available = data.get('is_available', True)
            existing.duration_minutes = duration_val
        else:
            rec = DoctorAvailability(
                doctor_id=doctor.id,
                date=dt,
                start_time=start_time,
                end_time=end_time,
                is_available=data.get('is_available', True),
                duration_minutes=duration_val
            )
            db.session.add(rec)

    if apply_to_next:
        # selected date + next 6 days (total 7 days)
        for i in range(7):
            upsert_for_date(availability_date + timedelta(days=i))
    else:
        upsert_for_date(availability_date)

    db.session.commit()
    return jsonify({'message': 'Availability updated successfully', 'applied_days': 7 if apply_to_next else 1})

@doctor_bp.route('/api/availability/<int:availability_id>', methods=['DELETE'])
@doctor_required
def delete_availability(availability_id):
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    
    availability = DoctorAvailability.query.filter_by(
        id=availability_id,
        doctor_id=doctor.id
    ).first_or_404()
    
    db.session.delete(availability)
    db.session.commit()
    
    return jsonify({'message': 'Availability deleted successfully'})

@doctor_bp.route('/api/slots', methods=['GET'])
@doctor_required
def get_slots_by_date():
    """Return slot list for the authenticated doctor for a specific date with booking info."""
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()

    q_date = request.args.get('date')
    if not q_date:
        return jsonify({'message': 'date is required'}), 400
    try:
        target_date = datetime.strptime(q_date, '%Y-%m-%d').date()
    except Exception:
        return jsonify({'message': 'invalid date'}), 400

    av = DoctorAvailability.query.filter_by(
        doctor_id=doctor.id,
        date=target_date,
        is_available=True
    ).first()
    if not av:
        return jsonify({'date': target_date.isoformat(), 'duration_minutes': None, 'slots': []})

    # Map appointments by time string
    appointments = Appointment.query.options(
        joinedload(Appointment.patient).joinedload(Patient.user)
    ).filter_by(
        doctor_id=doctor.id,
        date=target_date
    ).all()
    appt_by_time = {a.time.strftime('%H:%M'): a for a in appointments if a.status in ('Booked', 'Completed')}

    # Generate times using duration
    duration = av.duration_minutes or 30
    start_dt = datetime.combine(target_date, av.start_time)
    end_dt = datetime.combine(target_date, av.end_time)
    slots = []
    cur = start_dt
    while cur < end_dt:
        label = cur.strftime('%H:%M')
        a = appt_by_time.get(label)
        slots.append({
            'time': label,
            'available': a is None,
            'appointment_id': a.id if a else None,
            'patient_name': a.patient.user.name if a else None,
            'reason': a.reason if a else None,
            'status': a.status if a else None
        })
        cur = cur + timedelta(minutes=duration)

    return jsonify({'date': target_date.isoformat(), 'duration_minutes': duration, 'slots': slots})

@doctor_bp.route('/api/slots', methods=['DELETE'])
@doctor_required
def delete_free_slot():
    """Delete a specific free slot (remove it from availability) for the authenticated doctor.
    Expects query params: date=YYYY-MM-DD, time=HH:MM. Fails if the slot is booked/completed.
    Implementation adjusts the availability window by splitting or shrinking.
    """
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()

    q_date = request.args.get('date')
    q_time = request.args.get('time')
    if not q_date or not q_time:
        return jsonify({'message': 'date and time are required'}), 400
    try:
        target_date = datetime.strptime(q_date, '%Y-%m-%d').date()
        slot_time = datetime.strptime(q_time, '%H:%M').time()
    except Exception:
        return jsonify({'message': 'invalid date or time'}), 400

    av = DoctorAvailability.query.filter_by(
        doctor_id=doctor.id,
        date=target_date,
        is_available=True
    ).first()
    if not av:
        return jsonify({'message': 'No availability set for that date'}), 404

    # Ensure slot aligns to availability grid and lies within window
    duration = av.duration_minutes or 30
    start_dt = datetime.combine(target_date, av.start_time)
    end_dt = datetime.combine(target_date, av.end_time)
    slot_dt = datetime.combine(target_date, slot_time)
    if not (start_dt <= slot_dt < end_dt):
        return jsonify({'message': 'Slot out of availability window'}), 400
    # validate grid alignment
    valid_times = set()
    cur = start_dt
    while cur < end_dt:
        valid_times.add(cur.strftime('%H:%M'))
        cur = cur + timedelta(minutes=duration)
    if q_time not in valid_times:
        return jsonify({'message': 'Time is not a valid slot for this availability'}), 400

    # Check not booked
    conflict = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date == target_date,
        Appointment.time == slot_time,
        Appointment.status.in_(['Booked', 'Completed'])
    ).first()
    if conflict:
        return jsonify({'message': 'Cannot delete: slot is booked'}), 409

    slot_end_dt = slot_dt + timedelta(minutes=duration)

    # Cases to handle: remove [slot_dt, slot_end_dt) from [start_dt, end_dt)
    if slot_dt == start_dt and slot_end_dt >= end_dt:
        # Only one slot in this availability; delete the record
        db.session.delete(av)
        db.session.commit()
        return jsonify({'message': 'Slot removed and availability deleted for the date'})
    elif slot_dt == start_dt:
        # shrink start forward
        av.start_time = slot_end_dt.time()
        db.session.commit()
        return jsonify({'message': 'Slot removed'})
    elif slot_end_dt >= end_dt:
        # shrink end backward
        av.end_time = slot_dt.time()
        db.session.commit()
        return jsonify({'message': 'Slot removed'})
    else:
        # split into two windows: [start_dt, slot_dt) and [slot_end_dt, end_dt)
        # update existing to first window; create new for second
        av_end_before = av.end_time
        av.end_time = slot_dt.time()
        # second window
        new_av = DoctorAvailability(
            doctor_id=doctor.id,
            date=target_date,
            start_time=slot_end_dt.time(),
            end_time=av_end_before,
            is_available=True,
            duration_minutes=duration
        )
        db.session.add(new_av)
        db.session.commit()
        return jsonify({'message': 'Slot removed'})

@doctor_bp.route('/api/appointments/<int:appointment_id>/reschedule', methods=['PUT'])
@doctor_required
def reschedule_appointment_time(appointment_id):
    """Reschedule an appointment to a different time, possibly another date, validating against availability and conflicts."""
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()

    appt = Appointment.query.filter_by(id=appointment_id, doctor_id=doctor.id).first_or_404()
    data = request.get_json()
    new_time_str = data.get('time')
    if not new_time_str:
        return jsonify({'message': 'time is required'}), 400
    try:
        new_time = datetime.strptime(new_time_str, '%H:%M').time()
    except Exception:
        return jsonify({'message': 'invalid time'}), 400
    # Optional new date
    new_date_str = data.get('date')
    target_date = appt.date
    if new_date_str:
        try:
            target_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
        except Exception:
            return jsonify({'message': 'invalid date'}), 400

    # Check availability exists for target date
    av = DoctorAvailability.query.filter_by(
        doctor_id=doctor.id,
        date=target_date,
        is_available=True
    ).first()
    if not av:
        return jsonify({'message': 'No availability set for the target date'}), 400

    # Check time within window and matches slot multiple
    duration = av.duration_minutes or 30
    start_dt = datetime.combine(target_date, av.start_time)
    end_dt = datetime.combine(target_date, av.end_time)
    candidate_dt = datetime.combine(target_date, new_time)
    if not (start_dt <= candidate_dt < end_dt):
        return jsonify({'message': 'Selected time out of availability window'}), 400
    # Ensure selected time matches generated slots by duration
    cur = start_dt
    valid = set()
    while cur < end_dt:
        valid.add(cur.strftime('%H:%M'))
        cur = cur + timedelta(minutes=duration)
    if new_time.strftime('%H:%M') not in valid:
        return jsonify({'message': 'Selected time is not a valid slot'}), 400
    # Ensure not conflicting with other appt
    conflict = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date == target_date,
        Appointment.time == new_time,
        Appointment.id != appt.id,
        Appointment.status.in_(['Booked', 'Completed'])
    ).first()
    if conflict:
        return jsonify({'message': 'Selected slot is no longer available. Please choose another time.'}), 409

    appt.date = target_date
    appt.time = new_time
    db.session.commit()

    updated = Appointment.query.options(
        joinedload(Appointment.patient).joinedload(Patient.user),
        joinedload(Appointment.doctor).joinedload(Doctor.user),
        joinedload(Appointment.treatment)
    ).get(appt.id)
    return jsonify({'message': 'Appointment rescheduled', 'appointment': updated.to_dict() if updated else None})

@doctor_bp.route('/api/availability/by-date', methods=['DELETE'])
@doctor_required
def delete_availability_by_date():
    """Delete availability for a specific date if no booked/completed appointments exist."""
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()

    q_date = request.args.get('date')
    if not q_date:
        return jsonify({'message': 'date is required'}), 400
    try:
        target_date = datetime.strptime(q_date, '%Y-%m-%d').date()
    except Exception:
        return jsonify({'message': 'invalid date'}), 400

    av = DoctorAvailability.query.filter_by(doctor_id=doctor.id, date=target_date).first()
    if not av:
        return jsonify({'message': 'No availability set for that date'}), 404

    # Check for any booked/completed appointments on that date
    has_busy = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date == target_date,
        Appointment.status.in_(['Booked', 'Completed'])
    ).first()
    if has_busy:
        return jsonify({'message': 'Cannot delete: slots booked on this date'}), 409

    db.session.delete(av)
    db.session.commit()
    return jsonify({'message': 'Availability deleted for the date'})

@doctor_bp.route('/profile')
@doctor_required
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
            # attach doctor-specific info if available
            doctor = Doctor.query.filter_by(user_id=user.id).first()
            if doctor:
                profile_data.update({
                    'specialization': doctor.specialization or '',
                    'experience': doctor.experience or '',
                    'qualification': doctor.qualification or '',
                    'fee': getattr(doctor, 'fee', 0)
                })
    except Exception:
        profile_data = {}

    return render_template('doctor/profile.html', profile_data=profile_data)

@doctor_bp.route('/api/profile', methods=['GET'])
@doctor_required
def get_profile():
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    return jsonify(doctor.to_dict())

@doctor_bp.route('/api/profile', methods=['PUT'])
@doctor_required
def update_profile():
    user = User.query.get_or_404(current_user.id)
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    data = request.get_json()
    
    user.name = data.get('name', user.name)
    user.contact = data.get('contact', user.contact)
    
    if data.get('password'):
        user.password = generate_password_hash(data.get('password'))
    
    doctor.specialization = data.get('specialization', doctor.specialization)
    doctor.experience = data.get('experience', doctor.experience)
    doctor.qualification = data.get('qualification', doctor.qualification)
    if 'fee' in data and data.get('fee') is not None:
        try:
            doctor.fee = int(data.get('fee'))
        except Exception:
            pass
    
    db.session.commit()
    
    return jsonify({'message': 'Profile updated successfully', 'doctor': doctor.to_dict()})
