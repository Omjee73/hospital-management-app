// Human-readable main.js consolidating all mounts for Admin/Doctor/Patient dashboards and Admin Doctors UI
// Uses global Vue (from CDN) and a minimal fetch helper exposed as `window.http` (provided in base.html)
(function () {
	const start = Date.now();
	const maxWaitMs = 3000;
	function boot() {
		if (!window.Vue) {
			if (Date.now() - start < maxWaitMs) {
				return setTimeout(boot, 100);
			}
			console.error('[main.js] Vue failed to load within timeout; skipping mounts.');
			return;
		}
		const { createApp } = window.Vue;

		const mount = (Comp, id) => {
			const el = document.getElementById(id);
			if (el) createApp(Comp).mount(`#${id}`);
		};

	// Admin Doctors Component (ported from SFC to inline template)
	const AdminDoctors = {
		name: 'AdminDoctors',
		template: `
			<div>
				<div class="pt-3 pb-2 mb-3 border-bottom d-flex justify-content-between">
					<h1 class="h2">Manage Doctors</h1>
					<button class="btn btn-primary" @click="openAdd"><i class="bi bi-plus-circle"></i> Add Doctor</button>
				</div>

				<div class="mb-3">
					<input v-model="query" @input="search" class="form-control" placeholder="Search by name or specialization" />
				</div>

				<div class="table-responsive">
					<table class="table table-striped">
						<thead>
							<tr>
								<th>Name</th>
								<th>Email</th>
								<th>Specialization</th>
								<th>Department</th>
								<th>Experience</th>
								<th>Fee</th>
								<th>Status</th>
								<th>Actions</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="d in doctors" :key="d.id">
								<td>{{ d.name }}</td>
								<td>{{ d.email }}</td>
								<td>{{ d.specialization }}</td>
								<td>{{ d.department_name }}</td>
								<td>{{ d.experience }} years</td>
								<td>₹{{ d.fee || 0 }}</td>
								<td><span :class="d.is_active ? 'badge bg-success' : 'badge bg-danger'">{{ d.is_active ? 'Active' : 'Inactive' }}</span></td>
								<td>
									<button class="btn btn-sm btn-primary me-1" @click="openEdit(d)"><i class="bi bi-pencil"></i></button>
									<button class="btn btn-sm btn-danger me-1" v-if="d.is_active" @click="deactivate(d.id)"><i class="bi bi-trash"></i></button>
									<button class="btn btn-sm btn-success" v-if="!d.is_active" @click="activate(d.id)"><i class="bi bi-arrow-clockwise"></i></button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<!-- Add/Edit Modal -->
				<div class="modal" :class="{'show d-block': showModal}" tabindex="-1">
					<div class="modal-dialog">
						<div class="modal-content">
							<div class="modal-header">
								<h5 class="modal-title">{{ isEdit ? 'Edit' : 'Add' }} Doctor</h5>
								<button type="button" class="btn-close" @click="closeModal"></button>
							</div>
							<div class="modal-body">
								<div v-if="formError" class="alert alert-danger py-2">{{ formError }}</div>
								<div class="mb-3">
									<label class="form-label">Name</label>
									<input type="text" class="form-control" v-model="form.name" required :class="{'is-invalid': validationAttempted && !form.name}" />
									<div class="invalid-feedback">Name is required.</div>
								</div>
								<div class="mb-3" v-if="!isEdit">
									<label class="form-label">Email</label>
									<input type="email" class="form-control" v-model="form.email" required :class="{'is-invalid': validationAttempted && !form.email}" />
									<div class="invalid-feedback">Email is required.</div>
								</div>
								<div class="mb-3">
									<label class="form-label">Contact</label>
									<input type="text" class="form-control" v-model="form.contact" required :class="{'is-invalid': validationAttempted && !form.contact}" />
									<div class="invalid-feedback">Contact is required.</div>
								</div>
								<div class="mb-3">
									<label class="form-label">Department</label>
									<select class="form-control" v-model="form.department_id" required :class="{'is-invalid': validationAttempted && !form.department_id}">
										<option value="">Select Department</option>
										<option v-for="dept in departments" :key="dept.id" :value="dept.id">{{ dept.name }}</option>
									</select>
									<div class="invalid-feedback">Department is required.</div>
								</div>
								<div class="mb-3">
									<label class="form-label">Specialization</label>
									<input type="text" class="form-control" v-model="form.specialization" required :class="{'is-invalid': validationAttempted && !form.specialization}" />
									<div class="invalid-feedback">Specialization is required.</div>
								</div>
								<div class="mb-3">
									<label class="form-label">Experience (years)</label>
									<input type="number" class="form-control" v-model.number="form.experience" required :class="{'is-invalid': validationAttempted && (form.experience === '' || form.experience === null || form.experience < 0)}" />
									<div class="invalid-feedback">Valid non-negative experience is required.</div>
								</div>
								<div class="mb-3">
									<label class="form-label">Qualification</label>
									<input type="text" class="form-control" v-model="form.qualification" required :class="{'is-invalid': validationAttempted && !form.qualification}" />
									<div class="invalid-feedback">Qualification is required.</div>
								</div>
								<div class="mb-3">
									<label class="form-label">Consultation Fee (₹)</label>
									<input type="number" class="form-control" v-model.number="form.fee" min="0" required :class="{'is-invalid': validationAttempted && (form.fee === '' || form.fee === null || form.fee < 0)}" />
									<div class="invalid-feedback">Valid non-negative fee is required.</div>
								</div>
								<div class="mb-3" v-if="!isEdit">
									<label class="form-label">Password <span class="text-danger">*</span></label>
									<input type="password" class="form-control" v-model="form.password" required :class="{'is-invalid': validationAttempted && !form.password}" placeholder="Enter a secure password" />
									<div class="invalid-feedback">Password is required.</div>
								</div>
								<div class="mb-3" v-if="isEdit">
									<label class="form-label">New Password (leave blank to keep current)</label>
									<input type="password" class="form-control" v-model="form.password" placeholder="leave blank to keep" />
								</div>
							</div>
							<div class="modal-footer">
								<button type="button" class="btn btn-secondary" @click="closeModal">Close</button>
								<button type="button" class="btn btn-primary" :disabled="!canSave" @click="saveDoctor">Save</button>
							</div>
						</div>
					</div>
				</div>
				<div class="modal-backdrop fade" :class="{'show': showModal}" v-if="showModal"></div>
			</div>
		`,
		data() {
			return {
				doctors: [],
				departments: [],
				query: '',
				showModal: false,
				isEdit: false,
				form: {
					id: null,
					name: '',
					email: '',
					contact: '',
					department_id: '',
					specialization: '',
					experience: 0,
					qualification: '',
					fee: 0,
					password: ''
				},
				validationAttempted: false,
				formError: ''
			};
		},
		computed: {
			canSave() {
				const f = this.form;
				if (!this.isEdit) {
					return !!(f.name && f.email && f.contact && f.department_id && f.specialization && (f.experience === 0 || f.experience > -1) && f.qualification && (f.fee === 0 || f.fee > -1) && f.password);
				}
				return !!(f.name && f.contact && f.department_id && f.specialization && (f.experience === 0 || f.experience > -1) && f.qualification && (f.fee === 0 || f.fee > -1));
			}
		},
		async mounted() {
			await this.load();
			await this.loadDepartments();
		},
		methods: {
			async load() {
				try {
					const r = await http.get('/admin/api/doctors');
					this.doctors = r.data;
				} catch (e) {
					console.error(e);
				}
			},
			async loadDepartments() {
				try {
					const r = await http.get('/admin/api/departments');
					this.departments = r.data;
				} catch (e) {
					console.error(e);
				}
			},
			async search() {
				if (!this.query) return this.load();
				const r = await http.get(`/admin/search/doctors?q=${encodeURIComponent(this.query)}`);
				this.doctors = r.data;
			},
			openAdd() {
				this.isEdit = false;
				this.form = { id: null, name: '', email: '', contact: '', department_id: '', specialization: '', experience: 0, qualification: '', fee: 0, password: '' };
				this.showModal = true;
			},
			openEdit(d) {
				this.isEdit = true;
				this.form = { id: d.id, name: d.name, email: d.email, contact: d.contact, department_id: d.department_id, specialization: d.specialization, experience: d.experience, qualification: d.qualification, fee: d.fee || 0 };
				this.showModal = true;
			},
			closeModal() {
				this.showModal = false;
			},
			async saveDoctor() {
				try {
					this.validationAttempted = true;
					if (!this.validateForm()) return;
					const payload = { ...this.form };
					if (!this.isEdit) {
						payload.email = (payload.email || '').trim().toLowerCase();
						payload.password = (payload.password || '').trim();
					} else if (Object.prototype.hasOwnProperty.call(payload, 'password')) {
						payload.password = (payload.password || '').trim();
						if (!payload.password) delete payload.password;
					}
					if (this.isEdit) {
						const resp = await http.put(`/admin/api/doctors/${this.form.id}`, payload);
						const updated = resp.data && resp.data.doctor ? resp.data.doctor : null;
						if (updated) this.doctors = this.doctors.map(d => d.id === updated.id ? updated : d);
					} else {
						const resp = await http.post('/admin/api/doctors', payload);
						if (resp.data && resp.data.doctor) this.doctors.unshift(resp.data.doctor);
					}
					this.showModal = false;
					await this.load();
				} catch (e) {
					console.error(e);
					alert(e && e.response && e.response.data && e.response.data.message ? e.response.data.message : 'Error saving doctor');
				}
			},
			validateForm() {
				const f = this.form;
				const missing = [];
				if (!f.name) missing.push('name');
				if (!this.isEdit && !f.email) missing.push('email');
				if (!f.contact) missing.push('contact');
				if (!f.department_id) missing.push('department');
				if (!f.specialization) missing.push('specialization');
				if (f.experience === '' || f.experience === null || f.experience < 0) missing.push('experience');
				if (!f.qualification) missing.push('qualification');
				if (!this.isEdit && !f.password) missing.push('password');
				if (missing.length) { this.formError = 'Please provide: ' + missing.join(', '); return false; }
				if (!this.isEdit) {
					const email = (f.email || '').trim().toLowerCase();
					const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
					if (!emailPattern.test(email)) { this.formError = 'Please provide a valid email address.'; return false; }
					const pwd = (f.password || '').trim();
					if (pwd.length < 6) { this.formError = 'Password must be at least 6 characters.'; return false; }
				} else if (Object.prototype.hasOwnProperty.call(f, 'password') && f.password) {
					const newPwd = (f.password || '').trim();
					if (newPwd && newPwd.length < 6) { this.formError = 'New password must be at least 6 characters.'; return false; }
				}
				if (f.fee === '' || f.fee === null || f.fee < 0) { this.formError = 'Fee must be a non-negative number.'; return false; }
				this.formError = '';
				return true;
			},
			async deactivate(id) {
				try {
					await http.delete(`/admin/api/doctors/${id}`);
					this.doctors = this.doctors.map(d => d.id === id ? { ...d, is_active: false } : d);
					this.load();
				} catch (e) {
					console.error(e);
					alert('Error deactivating doctor');
				}
			},
			async activate(id) {
				try {
					const resp = await http.post(`/admin/api/doctors/${id}/activate`);
					if (resp.data && resp.data.doctor) {
						this.doctors = this.doctors.map(d => d.id === id ? resp.data.doctor : d);
					} else {
						this.doctors = this.doctors.map(d => d.id === id ? { ...d, is_active: true } : d);
					}
					this.load();
				} catch (e) {
					console.error(e);
					alert('Error activating doctor');
				}
			}
		}
	};

	const AdminOverview = {
		name: 'AdminOverview',
		template: `
			<div>
				<div class="pt-3 pb-2 mb-3 border-bottom"><h1 class="h2">Dashboard</h1></div>
				<div class="row mb-4">
					<div class="col-md-4 mb-3"><div class="card stat-card"><div class="card-body"><h6 class="text-muted">Active Doctors</h6><h2 class="mb-0">{{ stats.doctors }}</h2></div></div></div>
					<div class="col-md-4 mb-3"><div class="card stat-card"><div class="card-body"><h6 class="text-muted">Total Patients</h6><h2 class="mb-0">{{ stats.patients }}</h2></div></div></div>
					<div class="col-md-4 mb-3"><div class="card stat-card"><div class="card-body"><h6 class="text-muted">Booked Appointments</h6><h2 class="mb-0">{{ stats.appointments }}</h2></div></div></div>
				</div>
				<div class="card"><div class="card-header"><h5>Quick Actions</h5></div>
					<div class="card-body">
						<a href="/admin/doctors" class="btn btn-primary me-2"><i class="bi bi-plus-circle"></i> Add Doctor</a>
						<a href="/admin/patients" class="btn btn-secondary me-2"><i class="bi bi-eye"></i> View Patients</a>
						<a href="/admin/appointments" class="btn btn-info"><i class="bi bi-calendar"></i> View Appointments</a>
					</div>
				</div>
				<div class="row mt-4">
					<div class="col-md-6">
						<div class="card h-100"><div class="card-header">Appointments (Last 6 Months)</div>
							<div class="card-body"><canvas id="adminLineChart" class="chart-400"></canvas></div>
						</div></div>
					<div class="col-md-6">
						<div class="card h-100"><div class="card-header">Appointments by Status</div>
							<div class="card-body"><canvas id="adminPieChart" class="chart-400"></canvas></div>
						</div></div>
				</div>
			</div>
		`,
		data() { return { stats: { doctors: 0, patients: 0, appointments: 0 } }; },
		async mounted() { await this.loadStats(); await this.renderCharts(); },
		methods: {
			async loadStats() {
				try { const r = await http.get('/admin/stats'); this.stats = r.data; }
				catch (e) { console.error('Failed to load stats', e); }
			},
			async renderCharts() {
				try {
					const r = await http.get('/admin/stats/charts');
					const { monthly, statusDist } = r.data || {};
					if (monthly && document.getElementById('adminLineChart')) {
						new Chart(document.getElementById('adminLineChart'), {
							type: 'line',
							data: { labels: monthly.labels, datasets: [{ label: 'Appointments', data: monthly.data, borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,.1)', tension: .3 }] },
							options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
						});
					}
					if (statusDist && document.getElementById('adminPieChart')) {
						new Chart(document.getElementById('adminPieChart'), {
							type: 'pie',
							data: { labels: statusDist.labels, datasets: [{ data: statusDist.data, backgroundColor: ['#0d6efd','#198754','#dc3545'] }] },
							options: { responsive: true, maintainAspectRatio: false }
						});
					}
				} catch (e) { console.error('Failed to load admin charts', e); }
			}
		}
	};

	const DoctorDashboard = {
		name: 'DoctorDashboard',
		template: `
			<div class="doctor-dashboard">
				<div class="pt-3 pb-2 mb-3 border-bottom"><h1 class="h2">Dashboard</h1></div>
				<div class="row mb-4">
					<div class="col-md-4 mb-3"><div class="card stat-card h-100"><div class="card-body"><h6 class="text-muted">Upcoming Appointments</h6><h2 class="mb-0">{{ stats.upcoming_appointments }}</h2></div></div></div>
					<div class="col-md-4 mb-3"><div class="card stat-card h-100"><div class="card-body"><h6 class="text-muted">Total Patients</h6><h2 class="mb-0">{{ stats.total_patients }}</h2></div></div></div>
					<div class="col-md-4 mb-3"><div class="card stat-card h-100"><div class="card-body"><h6 class="text-muted">Completed</h6><h2 class="mb-0">{{ stats.completed_appointments }}</h2></div></div></div>
				</div>
				<div class="row mt-4">
					<div class="col-md-6">
						<div class="card h-100"><div class="card-header">Appointments (Last 6 Months)</div>
							<div class="card-body"><canvas id="doctorLineChart" class="chart-400"></canvas></div>
						</div></div>
					<div class="col-md-6">
						<div class="card h-100"><div class="card-header">Appointments by Status</div>
							<div class="card-body"><canvas id="doctorPieChart" class="chart-400"></canvas></div>
						</div></div>
				</div>
			</div>
		`,
		data() { return { stats: { upcoming_appointments: 0, total_patients: 0, completed_appointments: 0 } }; },
		async mounted() { await this.loadStats(); await this.renderCharts(); },
		methods: {
			async loadStats() {
				try { const r = await http.get('/doctor/stats'); this.stats = r.data; }
				catch (e) { console.error('Failed to load doctor stats', e); }
			},
			async renderCharts() {
				try {
					const r = await http.get('/doctor/stats/charts');
					const { monthly, statusDist } = r.data || {};
					if (monthly && document.getElementById('doctorLineChart')) {
						new Chart(document.getElementById('doctorLineChart'), {
							type: 'line',
							data: { labels: monthly.labels, datasets: [{ label: 'Appointments', data: monthly.data, borderColor: '#0d6efd', backgroundColor: 'rgba(13,110,253,.1)', tension: .3 }] },
							options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
						});
					}
					if (statusDist && document.getElementById('doctorPieChart')) {
						new Chart(document.getElementById('doctorPieChart'), {
							type: 'pie',
							data: { labels: statusDist.labels, datasets: [{ data: statusDist.data, backgroundColor: ['#0d6efd','#198754','#dc3545'] }] },
							options: { responsive: true, maintainAspectRatio: false }
						});
					}
				} catch (e) { console.error('Failed to load doctor charts', e); }
			}
		}
	};

	const PatientDashboard = {
		name: 'PatientDashboard',
		template: `
			<div class="patient-dashboard">
				<div class="pt-3 pb-2 mb-3 border-bottom"><h1 class="h2">Dashboard</h1></div>
				<div class="row mb-4">
					<div class="col-md-4 mb-3"><div class="card stat-card"><div class="card-body"><h6 class="text-muted">Upcoming Appointments</h6><h2 class="mb-0">{{ stats.upcoming }}</h2></div></div></div>
					<div class="col-md-4 mb-3"><div class="card stat-card"><div class="card-body"><h6 class="text-muted">Completed</h6><h2 class="mb-0">{{ stats.completed }}</h2></div></div></div>
					<div class="col-md-4 mb-3"><div class="card stat-card"><div class="card-body"><h6 class="text-muted">Cancelled</h6><h2 class="mb-0">{{ stats.cancelled }}</h2></div></div></div>
				</div>
				<div class="card"><div class="card-header"><h5>Quick Actions</h5></div>
					<div class="card-body">
						<a href="/patient/book-appointment" class="btn btn-primary"><i class="bi bi-calendar-plus"></i> Book New Appointment</a>
						<a href="/patient/history" class="btn btn-secondary ms-2"><i class="bi bi-clock-history"></i> View Medical History</a>
					</div>
				</div>

				<div class="pt-4 pb-2 mb-3 border-bottom d-flex align-items-center justify-content-between">
					<h2 class="h4 m-0">Explore Specialties & Departments</h2>
				</div>

				<div v-if="deptLoading" class="alert alert-info">Loading departments...</div>
				<div v-else>
					<div v-if="!departments.length" class="alert alert-warning">No departments found.</div>
					<div class="row g-3">
						<div class="col-12" v-for="dept in departments" :key="dept.id">
							<div class="card h-100">
								<div class="card-body">
									<div class="d-flex justify-content-between align-items-start">
										<div>
											<h5 class="card-title mb-1">{{ dept.name }}</h5>
											<p class="text-muted mb-2" v-if="dept.description">{{ dept.description }}</p>
										</div>
										<div class="text-end">
											<div class="small text-muted">Doctors: <strong>{{ dept.doctor_count }}</strong></div>
										</div>
									</div>
									<div v-if="dept.doctors && dept.doctors.length" class="table-responsive mt-3">
										<table class="table table-sm align-middle">
											<thead>
												<tr>
													<th>Name</th>
													<th>Specialization</th>
													<th>Experience</th>
													<th>Qualification</th>
													<th>Fee</th>
													<th>Contact</th>
													<th>Action</th>
												</tr>
											</thead>
											<tbody>
												<tr v-for="doc in dept.doctors" :key="doc.id">
													<td>{{ doc.name }}</td>
													<td>{{ doc.specialization }}</td>
													<td>{{ doc.experience }} yrs</td>
													<td>{{ doc.qualification }}</td>
													<td>₹{{ doc.fee || 0 }}</td>
													<td>{{ doc.contact }}</td>
													<td>
														<a class="btn btn-sm btn-outline-primary" :href="bookUrl(doc.id)"><i class="bi bi-calendar-plus"></i> Book</a>
													</td>
												</tr>
											</tbody>
										</table>
									</div>
									<div v-else class="text-muted">No active doctors listed for this department.</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		`,
		data() { return { stats: { upcoming: 0, completed: 0, cancelled: 0 }, departments: [], deptLoading: false }; },
		async mounted() { await this.loadStats(); await this.loadDepartments(); },
		methods: {
			async loadStats() {
				try { const r = await http.get('/patient/stats'); this.stats = r.data || { upcoming: 0, completed: 0, cancelled: 0 }; }
				catch (e) { console.error('Failed to load patient stats', e); }
			},
			async loadDepartments() {
				this.deptLoading = true;
				try {
					const r = await http.get('/patient/api/departments');
					this.departments = Array.isArray(r.data) ? r.data : [];
				} catch (e) {
					console.error('Failed to load departments', e);
					this.departments = [];
				} finally {
					this.deptLoading = false;
				}
			},
			bookUrl(doctorId) {
				return `/patient/book-appointment?doctor_id=${encodeURIComponent(doctorId)}`;
			}
		}
	};

		// Mounts
		mount(AdminDoctors, 'vue-root');
		mount(AdminOverview, 'dashboard-app');
		mount(DoctorDashboard, 'doctor-dashboard-app');
		mount(PatientDashboard, 'patient-dashboard-app');
	}
	boot();
})();
