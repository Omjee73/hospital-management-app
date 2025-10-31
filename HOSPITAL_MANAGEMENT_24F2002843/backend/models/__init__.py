from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'name': self.name,
            'contact': self.contact,
            'is_active': self.is_active
        }

class Department(db.Model):
    __tablename__ = 'departments'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    
    doctors = db.relationship('Doctor', backref='department', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description
        }

class Doctor(db.Model):
    __tablename__ = 'doctors'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    specialization = db.Column(db.String(100), nullable=False)
    experience = db.Column(db.Integer)
    qualification = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    # consultation fee in smallest currency unit or integer amount
    fee = db.Column(db.Integer, default=0)
    
    user = db.relationship('User', backref=db.backref('doctor_profile', uselist=False))
    appointments = db.relationship('Appointment', backref='doctor', lazy=True)
    availability = db.relationship('DoctorAvailability', backref='doctor', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.user.name,
            'email': self.user.email,
            'contact': self.user.contact,
            'department_id': self.department_id,
            'department_name': self.department.name,
            'specialization': self.specialization,
            'experience': self.experience,
            'qualification': self.qualification,
            'is_active': self.is_active,
            'fee': self.fee
        }

class DoctorAvailability(db.Model):
    __tablename__ = 'doctor_availability'
    
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    # duration of each appointment slot in minutes
    duration_minutes = db.Column(db.Integer, default=30)
    # optional JSON/text of custom slot times (comma-separated HH:MM or JSON array)
    custom_times = db.Column(db.Text)
    
    def to_dict(self):
        # parse custom_times to list of 'HH:MM' if present
        times_list = None
        if self.custom_times:
            try:
                import json
                parsed = json.loads(self.custom_times)
                if isinstance(parsed, list):
                    times_list = parsed
                else:
                    times_list = [t.strip() for t in str(self.custom_times).split(',') if t.strip()]
            except Exception:
                times_list = [t.strip() for t in str(self.custom_times).split(',') if t.strip()]
        return {
            'id': self.id,
            'doctor_id': self.doctor_id,
            'date': self.date.isoformat(),
            'start_time': self.start_time.strftime('%H:%M'),
            'end_time': self.end_time.strftime('%H:%M'),
            'is_available': self.is_available,
            'duration_minutes': self.duration_minutes,
            'custom_times': times_list
        }

class Patient(db.Model):
    __tablename__ = 'patients'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(10))
    address = db.Column(db.Text)
    blood_group = db.Column(db.String(5))
    emergency_contact = db.Column(db.String(20))
    
    user = db.relationship('User', backref=db.backref('patient_profile', uselist=False))
    appointments = db.relationship('Appointment', backref='patient', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.user.name,
            'email': self.user.email,
            'contact': self.user.contact,
            'is_active': getattr(self.user, 'is_active', True),
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'gender': self.gender,
            'address': self.address,
            'blood_group': self.blood_group,
            'emergency_contact': self.emergency_contact
        }

class Appointment(db.Model):
    __tablename__ = 'appointments'
    
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), default='Booked')
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    treatment = db.relationship('Treatment', backref='appointment', uselist=False, cascade='all, delete-orphan')
    
    def to_dict(self):
        # derive location from doctor's department if available
        try:
            location = self.doctor.department.name if self.doctor and self.doctor.department else None
        except Exception:
            location = None
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'patient_name': self.patient.user.name,
            'doctor_id': self.doctor_id,
            'doctor_name': self.doctor.user.name,
            'doctor_specialization': self.doctor.specialization,
            'doctor_fee': getattr(self.doctor, 'fee', 0),
            'date': self.date.isoformat(),
            'time': self.time.strftime('%H:%M'),
            'status': self.status,
            'reason': self.reason,
            'location': location,
            'treatment': self.treatment.to_dict() if self.treatment else None
        }

class Treatment(db.Model):
    __tablename__ = 'treatments'
    
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=False, unique=True)
    diagnosis = db.Column(db.Text)
    prescription = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'appointment_id': self.appointment_id,
            'diagnosis': self.diagnosis,
            'prescription': self.prescription,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
