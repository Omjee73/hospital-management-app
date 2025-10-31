from celery import Celery
from celery.schedules import crontab
from datetime import datetime, date, timedelta
import csv
import io
import os
import smtplib
import ssl
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import json
import urllib.request
import urllib.error
import pathlib
from email.utils import formatdate, make_msgid

# --- Load .env if present (no extra dependency) ---
def _load_env_from_file(env_path: str | None = None):
    """Load .env from a few likely locations:
    - explicit env_path
    - folder of this file (backend/.env)
    - parent of this folder (project/.env)
    - current working directory
    Does NOT override non-empty existing environment values.
    """
    loaded = []
    try:
        # Build candidate paths
        candidates = []
        if env_path:
            candidates.append(pathlib.Path(env_path))
        here = pathlib.Path(__file__).resolve().parent
        candidates.append(here / '.env')
        candidates.append(here.parent / '.env')
        candidates.append(pathlib.Path.cwd() / '.env')
        # De-duplicate while preserving order
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

        with chosen.open('r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # Only set if missing or empty in current env
                if key and val and (key not in os.environ or not os.environ.get(key)):
                    os.environ[key] = val
                    loaded.append(key)
        # Brief summary (no secrets)
        flags = {
            'SMTP_HOST': bool(os.getenv('SMTP_HOST')),
            'SMTP_USER': bool(os.getenv('SMTP_USER')),
            'SMTP_FROM': bool(os.getenv('SMTP_FROM')),
            'ADMIN_EMAIL': bool(os.getenv('ADMIN_EMAIL')),
            'GCHAT_WEBHOOK_URL': bool(os.getenv('GCHAT_WEBHOOK_URL')),
        }
        print('[ENV] Loaded .env from', str(chosen))
        if loaded:
            print('[ENV] New keys set:', ','.join(loaded))
        print('[ENV] Flags:', flags)
    except Exception as e:
        print('[ENV] Failed to load .env:', e)

_load_env_from_file()

celery = Celery(
    'hospital_tasks',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0'
)

celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# --- Notification helpers ---

def _send_email(subject: str, html_body: str, to_addrs: list[str], attachments: list[tuple[str, bytes]] | None = None):
    host = os.getenv('SMTP_HOST')
    port = int(os.getenv('SMTP_PORT', '587'))
    user = os.getenv('SMTP_USER')
    password = os.getenv('SMTP_PASS')
    sender_email = os.getenv('SMTP_FROM', user or 'no-reply@localhost')
    sender_name = os.getenv('SMTP_FROM_NAME')
    smtp_debug = os.getenv('SMTP_DEBUG') == '1'
    smtp_bcc = [addr.strip() for addr in os.getenv('SMTP_BCC', '').split(',') if addr.strip()]
    if not host or not to_addrs:
        print('[EMAIL] Missing config; skipping email send', {
            'has_host': bool(host),
            'recipients_count': len(to_addrs) if to_addrs else 0
        })
        return False

    # Build a multipart/alternative for better deliverability (plain + HTML)
    msg = MIMEMultipart('mixed')
    msg['From'] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    msg['To'] = ', '.join(to_addrs)
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    # Optional Reply-To to route responses back to sender
    msg['Reply-To'] = sender_email
    try:
        msg['Message-ID'] = make_msgid()
    except Exception:
        pass

    alt = MIMEMultipart('alternative')
    # Very simple HTML->text fallback to reduce spam classification
    text_body = re.sub(r'<[^>]+>', '', html_body or '')
    alt.attach(MIMEText(text_body or 'This is an HTML message. Please view in an HTML-capable mail client.', 'plain', 'utf-8'))
    alt.attach(MIMEText(html_body or '', 'html', 'utf-8'))
    msg.attach(alt)

    for att_name, att_bytes in (attachments or []):
        part = MIMEApplication(att_bytes)
        part.add_header('Content-Disposition', 'attachment', filename=att_name)
        msg.attach(part)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            if smtp_debug:
                server.set_debuglevel(1)
            server.starttls(context=context)
            if user and password:
                server.login(user, password)
            # Merge BCC into actual envelope recipients but keep BCC header implicit
            envelope_rcpts = list(dict.fromkeys((to_addrs or []) + smtp_bcc))
            server.sendmail(sender_email, envelope_rcpts, msg.as_string())
        print('[EMAIL] Sent:', subject, 'to', to_addrs)
        return True
    except Exception as e:
        print('[EMAIL] Failed:', e)
        return False


def _send_gchat_card(text: str):
    webhook = os.getenv('GCHAT_WEBHOOK_URL')
    if not webhook:
        return False
    payload = {
        'text': text
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            _ = resp.read()
        print('[GCHAT] Posted')
        return True
    except urllib.error.HTTPError as e:
        print('[GCHAT] HTTP error:', e.code, e.read())
    except Exception as e:
        print('[GCHAT] Failed:', e)
    return False

def _send_gchat_csv_inline(filename: str, csv_text: str, max_chars_per_msg: int = 3500, max_messages: int = 10) -> bool:
    """Send CSV content inline to Google Chat as code blocks (no extra header text).
    Returns True if at least one message was sent successfully.
    """
    webhook = os.getenv('GCHAT_WEBHOOK_URL')
    if not webhook:
        return False

    # Split into chunks by line while respecting per-message size limits
    lines = csv_text.splitlines()
    chunks = []
    cur = []
    cur_len = 0
    # Leave headroom for wrapper/backticks and prefix text
    payload_limit = max(500, max_chars_per_msg - 200)
    for line in lines:
        line_len = len(line) + 1  # include newline
        if cur_len + line_len > payload_limit and cur:
            chunks.append('\n'.join(cur))
            cur = [line]
            cur_len = line_len
        else:
            cur.append(line)
            cur_len += line_len
    if cur:
        chunks.append('\n'.join(cur))

    # Cap the number of messages to avoid flooding
    truncated = False
    if len(chunks) > max_messages:
        chunks = chunks[:max_messages]
        truncated = True

    sent_any = False
    for chunk in chunks:
        text = f"```csv\n{chunk}\n```"
        if _send_gchat_card(text):
            sent_any = True
    return sent_any

@celery.task(name='daily_appointment_reminders')
def send_daily_reminders():
    from app import app
    from models import db, Appointment, Patient
    
    with app.app_context():
        # Allow override of reminder hour via env; schedule remains set in beat below
        today = date.today()
        appointments = Appointment.query.filter(
            Appointment.date == today,
            Appointment.status == 'Booked'
        ).all()
        
        for apt in appointments:
            patient_email = apt.patient.user.email
            doctor_name = apt.doctor.user.name
            time_str = apt.time.strftime('%H:%M')
            
            # Prefer Google Chat webhook if configured; otherwise try email; otherwise log
            text = f"Reminder: You have an appointment with Dr. {doctor_name} today at {time_str}."
            sent = _send_gchat_card(text)
            if not sent and patient_email:
                html = f"""
                <p>Hello,</p>
                <p>This is a reminder for your appointment with <strong>Dr. {doctor_name}</strong> today at <strong>{time_str}</strong>.</p>
                <p>Please arrive 10 minutes early.</p>
                <p>— Hospital</p>
                """
                _send_email('Appointment Reminder', html, [patient_email])
            print(f"[REMINDER] Processed reminder for {patient_email} at {time_str}")
        
        return f"Sent {len(appointments)} reminders"

@celery.task(name='monthly_doctor_reports')
def generate_monthly_reports():
    from app import app
    from models import db, Doctor, Appointment
    
    with app.app_context():
        first_day_last_month = date.today().replace(day=1) - timedelta(days=1)
        first_day_last_month = first_day_last_month.replace(day=1)
        last_day_last_month = date.today().replace(day=1) - timedelta(days=1)
        
        doctors = Doctor.query.filter_by(is_active=True).all()
        
        for doctor in doctors:
            appointments = Appointment.query.filter(
                Appointment.doctor_id == doctor.id,
                Appointment.date >= first_day_last_month,
                Appointment.date <= last_day_last_month
            ).all()
            
            completed = len([a for a in appointments if a.status == 'Completed'])
            cancelled = len([a for a in appointments if a.status == 'Cancelled'])
            pending = len([a for a in appointments if a.status not in ('Completed','Cancelled')])

            rows = []
            for a in appointments:
                diag = (a.treatment.diagnosis if a.treatment else '') or ''
                pres = (a.treatment.prescription if a.treatment else '') or ''
                notes = (a.treatment.notes if a.treatment else '') or ''
                rows.append(f"<tr><td>{a.date}</td><td>{a.time.strftime('%H:%M')}</td><td>{a.patient.user.name}</td><td>{a.status}</td><td>{diag}</td><td>{pres}</td><td>{notes}</td></tr>")

            report = f"""
            <html>
            <body>
                <h2>Monthly Report for Dr. {doctor.user.name}</h2>
                <p>Period: {first_day_last_month} to {last_day_last_month}</p>
                <ul>
                  <li>Total Appointments: {len(appointments)}</li>
                  <li>Completed: {completed}</li>
                  <li>Cancelled: {cancelled}</li>
                  <li>Pending/Booked: {pending}</li>
                </ul>
                <hr/>
                <table border="1" cellspacing="0" cellpadding="6">
                  <thead><tr><th>Date</th><th>Time</th><th>Patient</th><th>Status</th><th>Diagnosis</th><th>Prescription</th><th>Notes</th></tr></thead>
                  <tbody>{''.join(rows)}</tbody>
                </table>
            </body>
            </html>
            """
            # Try email to doctor
            doctor_email = doctor.user.email
            _send_email(
                subject=f"Monthly Activity Report - Dr. {doctor.user.name} ({first_day_last_month} to {last_day_last_month})",
                html_body=report,
                to_addrs=[doctor_email] if doctor_email else [],
            )
            print(f"[REPORT] Generated & attempted to email report for Dr. {doctor.user.name}: {doctor_email}")
        
        return f"Generated {len(doctors)} reports"

@celery.task(name='export_patient_history')
def export_patient_history_task(patient_id):
    from app import app
    from models import db, Patient, Appointment
    
    with app.app_context():
        patient = Patient.query.get(patient_id)
        appointments = Appointment.query.filter_by(
            patient_id=patient_id,
            status='Completed'
        ).all()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['User ID', 'Username', 'Doctor', 'Doctor Specialization', 'Appointment Date', 'Appointment Time', 'Diagnosis', 'Prescription', 'Notes'])
        
        for apt in appointments:
            writer.writerow([
                patient.user_id,
                patient.user.name,
                apt.doctor.user.name,
                apt.doctor.specialization,
                apt.date,
                apt.time.strftime('%H:%M') if apt.time else '',
                apt.treatment.diagnosis if apt.treatment else '',
                apt.treatment.prescription if apt.treatment else '',
                apt.treatment.notes if apt.treatment else ''
            ])
        
        csv_data = output.getvalue()
        filename = f'patient_{patient_id}_history_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        os.makedirs('exports', exist_ok=True)
        file_path = os.path.join('exports', filename)
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            f.write(csv_data)

        # Notify patient via email (attachment) first; fallback to Chat inline if email fails.
        subject = 'Your medical history export is ready'
        html = f"""
        <p>Hello {patient.user.name},</p>
        <p>Your medical history export has been generated. We've attached the CSV file to this email.</p>
        <p>— Hospital</p>
        """
        # Prepare recipients: patient and optional admin
        to_addrs = []
        if patient.user.email:
            to_addrs.append(patient.user.email)
        admin_email = os.getenv('ADMIN_EMAIL')
        if admin_email and admin_email not in to_addrs:
            to_addrs.append(admin_email)

        email_ok = False
        try:
            if to_addrs:
                email_ok = _send_email(subject, html, to_addrs, attachments=[(filename, csv_data.encode('utf-8'))])
        except Exception:
            email_ok = False

        # Fallback: send CSV inline to Google Chat (only if email failed)
        if not email_ok:
            _send_gchat_csv_inline(filename, csv_data)

        print(f"[EXPORT] CSV exported for patient {patient.user.email}: {file_path}")
        
        return file_path

# --- Backward compatibility: accept legacy task name ---
# Some older parts of the system (or leftover queued messages) may publish
# 'celery_app.export_patient_data_csv'. Register a shim that invokes the
# new implementation so those messages are processed instead of discarded.
@celery.task(name='celery_app.export_patient_data_csv')
def legacy_export_patient_data_csv(patient_id):
    # Execute synchronously in the same worker process
    return export_patient_history_task(patient_id)

celery.conf.beat_schedule = {
    'daily-reminders': {
        'task': 'daily_appointment_reminders',
        # Default 8 AM UTC; adjust via env REMINDER_HOUR / REMINDER_MIN if desired
        'schedule': crontab(hour=int(os.getenv('REMINDER_HOUR', '8')), minute=int(os.getenv('REMINDER_MIN', '0'))),
    },
    'monthly-reports': {
        'task': 'monthly_doctor_reports',
        'schedule': crontab(day_of_month=1, hour=int(os.getenv('REPORT_HOUR', '9')), minute=int(os.getenv('REPORT_MIN', '0'))),
    },
}
