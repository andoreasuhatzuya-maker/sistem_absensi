from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, send_from_directory, flash
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, time, timedelta
from sqlalchemy import event, or_, text, UniqueConstraint, Index
from sqlalchemy.engine import Engine
from sqlalchemy.orm import joinedload
from io import BytesIO
import os
import uuid

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


# ============================================================
# KONFIGURASI
# ============================================================

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("ABSENSI_SECRET_KEY", "kunci-rahasia-absensi-ganti-ini")
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
STATUS_VALID = ["Masuk", "Sakit", "Izin", "Tidak Masuk"]

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)


@event.listens_for(Engine, "connect")
def aktifkan_foreign_key_sqlite(dbapi_connection, connection_record):
    """SQLite tidak menyalakan foreign key secara default."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Silakan login terlebih dahulu."


@app.errorhandler(413)
def file_terlalu_besar(error):
    flash("Ukuran file melebihi batas maksimal 10 MB.", "error")
    return redirect(request.referrer or url_for("pengajuan"))


# ============================================================
# MODEL DATABASE
# ============================================================

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class Karyawan(db.Model):
    __table_args__ = (
        Index("ix_karyawan_nama", "nama"),
        Index("ix_karyawan_status_aktif", "status_aktif"),
    )

    id = db.Column(db.Integer, primary_key=True)
    nik = db.Column(db.String(20), unique=True, nullable=False)
    nama = db.Column(db.String(100), nullable=False)
    jabatan = db.Column(db.String(100), nullable=False)
    departemen = db.Column(db.String(100))
    status_aktif = db.Column(db.Boolean, default=True)

    absensi = db.relationship("Absensi", backref="karyawan", lazy=True)
    pengajuan = db.relationship("Pengajuan", backref="karyawan", lazy=True)


class Absensi(db.Model):
    __table_args__ = (
        UniqueConstraint("karyawan_id", "tanggal", name="uq_absensi_karyawan_tanggal"),
        Index("ix_absensi_tanggal", "tanggal"),
        Index("ix_absensi_status", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    karyawan_id = db.Column(db.Integer, db.ForeignKey("karyawan.id", ondelete="RESTRICT"), nullable=False)
    tanggal = db.Column(db.Date, nullable=False)
    jam_masuk = db.Column(db.Time)
    jam_pulang = db.Column(db.Time)
    status = db.Column(db.String(20), nullable=False)
    keterangan = db.Column(db.Text)

    lembur = db.relationship("Lembur", backref="absensi", lazy=True, uselist=False,
                             cascade="all, delete-orphan")


class Lembur(db.Model):
    __table_args__ = (
        UniqueConstraint("absensi_id", name="uq_lembur_absensi"),
    )

    id = db.Column(db.Integer, primary_key=True)
    absensi_id = db.Column(db.Integer, db.ForeignKey("absensi.id", ondelete="CASCADE"), nullable=False)
    jam_mulai = db.Column(db.Time)
    jam_selesai = db.Column(db.Time)
    total_jam = db.Column(db.Float)
    keterangan = db.Column(db.Text)


class Pengajuan(db.Model):
    __table_args__ = (
        UniqueConstraint("karyawan_id", "tanggal", name="uq_pengajuan_karyawan_tanggal"),
        UniqueConstraint("absensi_id", name="uq_pengajuan_absensi"),
        Index("ix_pengajuan_tanggal", "tanggal"),
        Index("ix_pengajuan_status", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    karyawan_id = db.Column(db.Integer, db.ForeignKey("karyawan.id", ondelete="RESTRICT"), nullable=False)
    absensi_id = db.Column(db.Integer, db.ForeignKey("absensi.id", ondelete="SET NULL"))
    tanggal = db.Column(db.Date, nullable=False)
    jenis = db.Column(db.String(20), nullable=False)
    alasan = db.Column(db.Text, nullable=False)
    bukti = db.Column(db.String(255))
    status = db.Column(db.String(20), default="Disetujui")
    keterangan_admin = db.Column(db.Text)

    absensi_terkait = db.relationship("Absensi", foreign_keys=[absensi_id])


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(Admin, int(user_id))
    except (TypeError, ValueError):
        return None


# ============================================================
# HELPER
# ============================================================

def file_diizinkan(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def parse_date(value, default=None):
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def format_tanggal(value):
    return value.strftime("%d-%m-%Y") if value else "-"


def get_absensi_harian(tanggal, hanya_aktif=True):
    query = Karyawan.query
    if hanya_aktif:
        query = query.filter_by(status_aktif=True)
    karyawan_list = query.order_by(Karyawan.nama.asc()).all()

    data_map = {
        item.karyawan_id: item
        for item in Absensi.query.filter_by(tanggal=tanggal).all()
    }

    hasil = []
    for karyawan in karyawan_list:
        data = data_map.get(karyawan.id)
        hasil.append({
            "karyawan": karyawan,
            "absensi": data,
            "status": data.status if data else "Belum Diinput",
            "jam_masuk": data.jam_masuk if data else None,
            "jam_pulang": data.jam_pulang if data else None,
            "keterangan": data.keterangan if data else "Belum ada data absensi",
        })
    return hasil


def hitung_rekap(data):
    return {
        "Masuk": sum(1 for item in data if item["status"] == "Masuk"),
        "Sakit": sum(1 for item in data if item["status"] == "Sakit"),
        "Izin": sum(1 for item in data if item["status"] == "Izin"),
        "Tidak Masuk": sum(1 for item in data if item["status"] == "Tidak Masuk"),
        "Belum Diinput": sum(1 for item in data if item["status"] == "Belum Diinput"),
    }


def absensi_untuk_laporan(tanggal_mulai, tanggal_selesai):
    return Absensi.query.options(
        joinedload(Absensi.karyawan), joinedload(Absensi.lembur)
    ).filter(
        Absensi.tanggal >= tanggal_mulai,
        Absensi.tanggal <= tanggal_selesai
    ).order_by(Absensi.tanggal.asc(), Absensi.karyawan_id.asc()).all()


@app.context_processor
def utility_processor():
    return {"hari_nama": HARI, "format_tanggal": format_tanggal, "date": date, "timedelta": timedelta}


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = Admin.query.filter_by(username=username).first()

        if admin and check_password_hash(admin.password, password):
            login_user(admin)
            return redirect(url_for("dashboard"))

        return render_template("login.html", error="Username atau password salah.")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/buat-admin")
def buat_admin():
    # Route ini dipertahankan untuk instalasi pertama.
    if Admin.query.first():
        return "Admin sudah ada. Silakan login."

    admin = Admin(username="admin", password=generate_password_hash("admin123"))
    db.session.add(admin)
    db.session.commit()
    return "Admin berhasil dibuat. Username: admin | Password: admin123"


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/")
def home():
    return redirect(url_for("dashboard")) if current_user.is_authenticated else redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    hari_ini = date.today()
    data = get_absensi_harian(hari_ini)
    rekap = hitung_rekap(data)

    return render_template(
        "dashboard.html",
        hari_ini=hari_ini,
        total_karyawan=len(data),
        total_masuk=rekap["Masuk"],
        total_sakit=rekap["Sakit"],
        total_izin=rekap["Izin"],
        total_tidak_masuk=rekap["Tidak Masuk"],
        total_belum=rekap["Belum Diinput"],
        absensi_hari_ini=data,
    )


# ============================================================
# KARYAWAN
# ============================================================

@app.route("/karyawan")
@login_required
def karyawan():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "aktif")

    query = Karyawan.query
    if status == "aktif":
        query = query.filter_by(status_aktif=True)
    elif status == "nonaktif":
        query = query.filter_by(status_aktif=False)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Karyawan.nik.ilike(like), Karyawan.nama.ilike(like),
                Karyawan.jabatan.ilike(like), Karyawan.departemen.ilike(like))
        )

    daftar = query.order_by(Karyawan.status_aktif.desc(), Karyawan.nama.asc()).all()
    return render_template("karyawan.html", daftar_karyawan=daftar, q=q, status=status)


@app.route("/karyawan/tambah", methods=["GET", "POST"])
@login_required
def tambah_karyawan():
    if request.method == "POST":
        nik = request.form.get("nik", "").strip()
        nama = request.form.get("nama", "").strip()
        jabatan = request.form.get("jabatan", "").strip()
        departemen = request.form.get("departemen", "").strip()

        if not nik or not nama or not jabatan:
            return render_template("tambah_karyawan.html", error="NIK, nama, dan jabatan wajib diisi.")
        if Karyawan.query.filter_by(nik=nik).first():
            return render_template("tambah_karyawan.html", error="NIK tersebut sudah terdaftar.")

        db.session.add(Karyawan(nik=nik, nama=nama, jabatan=jabatan,
                                departemen=departemen, status_aktif=True))
        db.session.commit()
        flash("Karyawan berhasil ditambahkan.", "success")
        return redirect(url_for("karyawan"))

    return render_template("tambah_karyawan.html")


@app.route("/karyawan/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_karyawan(id):
    karyawan_obj = db.session.get(Karyawan, id)
    if not karyawan_obj:
        return "Karyawan tidak ditemukan", 404

    if request.method == "POST":
        nik = request.form.get("nik", "").strip()
        nama = request.form.get("nama", "").strip()
        jabatan = request.form.get("jabatan", "").strip()
        departemen = request.form.get("departemen", "").strip()
        if not nik or not nama or not jabatan:
            return render_template(
                "edit_karyawan.html", karyawan=karyawan_obj,
                error="NIK, nama, dan jabatan wajib diisi."
            )
        duplikat = Karyawan.query.filter(Karyawan.nik == nik, Karyawan.id != id).first()
        if duplikat:
            return render_template("edit_karyawan.html", karyawan=karyawan_obj,
                                   error="NIK tersebut sudah digunakan karyawan lain.")

        karyawan_obj.nik = nik
        karyawan_obj.nama = nama
        karyawan_obj.jabatan = jabatan
        karyawan_obj.departemen = departemen
        db.session.commit()
        flash("Data karyawan berhasil diperbarui.", "success")
        return redirect(url_for("karyawan"))

    return render_template("edit_karyawan.html", karyawan=karyawan_obj)


@app.route("/karyawan/nonaktif/<int:id>", methods=["POST"])
@login_required
def nonaktif_karyawan(id):
    obj = db.session.get(Karyawan, id)
    if not obj:
        return "Karyawan tidak ditemukan", 404
    obj.status_aktif = False
    db.session.commit()
    flash(f"{obj.nama} dinonaktifkan. Riwayat lama tetap aman.", "success")
    return redirect(url_for("karyawan"))


@app.route("/karyawan/aktif/<int:id>", methods=["POST"])
@login_required
def aktifkan_karyawan(id):
    obj = db.session.get(Karyawan, id)
    if not obj:
        return "Karyawan tidak ditemukan", 404
    obj.status_aktif = True
    db.session.commit()
    flash(f"{obj.nama} diaktifkan kembali.", "success")
    return redirect(url_for("karyawan", status="aktif"))


# ============================================================
# ABSENSI HARIAN
# ============================================================

@app.route("/absensi")
@login_required
def absensi():
    tanggal = parse_date(request.args.get("tanggal"), date.today())
    data = get_absensi_harian(tanggal)
    rekap = hitung_rekap(data)
    return render_template("absensi.html", tanggal=tanggal, data_absensi=data, rekap=rekap)


@app.route("/absensi/tutup", methods=["POST"])
@login_required
def tutup_absensi():
    tanggal = parse_date(request.form.get("tanggal"), date.today())
    aktif = Karyawan.query.filter_by(status_aktif=True).all()
    dibuat = 0

    for karyawan in aktif:
        ada = Absensi.query.filter_by(karyawan_id=karyawan.id, tanggal=tanggal).first()
        if not ada:
            db.session.add(Absensi(
                karyawan_id=karyawan.id,
                tanggal=tanggal,
                status="Tidak Masuk",
                keterangan="Otomatis ditandai Tidak Masuk saat absensi ditutup."
            ))
            dibuat += 1

    db.session.commit()
    flash(f"Absensi {format_tanggal(tanggal)} ditutup. {dibuat} karyawan ditandai Tidak Masuk.", "success")
    return redirect(url_for("absensi", tanggal=tanggal.isoformat()))


@app.route("/absensi/data-contoh", methods=["POST"])
@login_required
def data_contoh_absensi():
    # Fitur contoh hanya untuk testing. Tidak menghapus data lama.
    aktif = Karyawan.query.filter_by(status_aktif=True).order_by(Karyawan.nama.asc()).all()
    if not aktif:
        flash("Belum ada karyawan aktif untuk dibuatkan data contoh.", "error")
        return redirect(url_for("absensi"))

    senin = date.today() - timedelta(days=date.today().weekday())
    pola = ["Masuk", "Masuk", "Sakit", "Izin", "Masuk", "Tidak Masuk", "Tidak Masuk"]

    for offset in range(7):
        tanggal = senin + timedelta(days=offset)
        for index, karyawan_obj in enumerate(aktif):
            if Absensi.query.filter_by(karyawan_id=karyawan_obj.id, tanggal=tanggal).first():
                continue
            status = pola[(offset + index) % len(pola)]
            db.session.add(Absensi(
                karyawan_id=karyawan_obj.id,
                tanggal=tanggal,
                jam_masuk=time(8, (index * 5) % 20) if status == "Masuk" else None,
                jam_pulang=time(17, 0) if status == "Masuk" else None,
                status=status,
                keterangan="Data contoh" if status != "Masuk" else ""
            ))

    db.session.commit()
    flash("Data contoh satu minggu berhasil dibuat.", "success")
    return redirect(url_for("absensi", tanggal=senin.isoformat()))


@app.route("/absensi/reset", methods=["POST"])
@login_required
def reset_absensi():
    # Reset aman: hanya menandai tanggal tertentu yang belum punya data sebagai Tidak Masuk.
    tanggal = parse_date(request.form.get("tanggal"), date.today())
    aktif = Karyawan.query.filter_by(status_aktif=True).all()
    dibuat = 0
    for karyawan_obj in aktif:
        if not Absensi.query.filter_by(karyawan_id=karyawan_obj.id, tanggal=tanggal).first():
            db.session.add(Absensi(
                karyawan_id=karyawan_obj.id,
                tanggal=tanggal,
                status="Tidak Masuk",
                keterangan="Otomatis ditandai Tidak Masuk."
            ))
            dibuat += 1
    db.session.commit()
    flash(f"Tidak ada data yang dihapus. {dibuat} karyawan ditandai Tidak Masuk untuk {format_tanggal(tanggal)}.", "success")
    return redirect(url_for("absensi", tanggal=tanggal.isoformat()))


@app.route("/absensi/tambah", methods=["GET", "POST"])
@login_required
def tambah_absensi():
    daftar_karyawan = Karyawan.query.filter_by(status_aktif=True).order_by(Karyawan.nama.asc()).all()
    tanggal_default = request.args.get("tanggal", date.today().isoformat())

    if request.method == "POST":
        karyawan_id = request.form.get("karyawan_id")
        tanggal = parse_date(request.form.get("tanggal"))
        status = request.form.get("status")
        jam_masuk = parse_time(request.form.get("jam_masuk"))
        jam_pulang = parse_time(request.form.get("jam_pulang"))
        keterangan = request.form.get("keterangan", "").strip()

        if not karyawan_id or not tanggal or status not in STATUS_VALID:
            return render_template("tambah_absensi.html", daftar_karyawan=daftar_karyawan,
                                   error="Data absensi belum lengkap.", tanggal_default=tanggal_default)

        if Absensi.query.filter_by(karyawan_id=int(karyawan_id), tanggal=tanggal).first():
            return render_template("tambah_absensi.html", daftar_karyawan=daftar_karyawan,
                                   error="Karyawan tersebut sudah memiliki absensi pada tanggal itu.",
                                   tanggal_default=tanggal.isoformat())

        if status == "Masuk" and not jam_masuk:
            return render_template("tambah_absensi.html", daftar_karyawan=daftar_karyawan,
                                   error="Jam masuk wajib diisi untuk status Masuk.",
                                   tanggal_default=tanggal.isoformat())
        if status != "Masuk":
            jam_masuk = None
            jam_pulang = None

        db.session.add(Absensi(karyawan_id=int(karyawan_id), tanggal=tanggal,
                               jam_masuk=jam_masuk, jam_pulang=jam_pulang,
                               status=status, keterangan=keterangan))
        db.session.commit()
        flash("Absensi berhasil ditambahkan.", "success")
        return redirect(url_for("absensi", tanggal=tanggal.isoformat()))

    return render_template("tambah_absensi.html", daftar_karyawan=daftar_karyawan,
                           tanggal_default=tanggal_default)


@app.route("/absensi/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_absensi(id):
    absensi_obj = db.session.get(Absensi, id)
    if not absensi_obj:
        return "Data absensi tidak ditemukan", 404

    daftar_karyawan = Karyawan.query.order_by(Karyawan.nama.asc()).all()
    if request.method == "POST":
        karyawan_id = request.form.get("karyawan_id")
        tanggal = parse_date(request.form.get("tanggal"))
        status = request.form.get("status")
        jam_masuk = parse_time(request.form.get("jam_masuk"))
        jam_pulang = parse_time(request.form.get("jam_pulang"))
        keterangan = request.form.get("keterangan", "").strip()

        if not karyawan_id or not tanggal or status not in STATUS_VALID:
            return render_template("edit_absensi.html", absensi=absensi_obj,
                                   daftar_karyawan=daftar_karyawan, error="Data belum lengkap.")

        duplikat = Absensi.query.filter(
            Absensi.karyawan_id == int(karyawan_id),
            Absensi.tanggal == tanggal,
            Absensi.id != id
        ).first()
        if duplikat:
            return render_template("edit_absensi.html", absensi=absensi_obj,
                                   daftar_karyawan=daftar_karyawan,
                                   error="Karyawan tersebut sudah memiliki absensi pada tanggal itu.")

        if status == "Masuk" and not jam_masuk:
            return render_template("edit_absensi.html", absensi=absensi_obj,
                                   daftar_karyawan=daftar_karyawan,
                                   error="Jam masuk wajib diisi untuk status Masuk.")
        if status != "Masuk":
            jam_masuk = None
            jam_pulang = None

        absensi_obj.karyawan_id = int(karyawan_id)
        absensi_obj.tanggal = tanggal
        absensi_obj.jam_masuk = jam_masuk
        absensi_obj.jam_pulang = jam_pulang
        absensi_obj.status = status
        absensi_obj.keterangan = keterangan
        db.session.commit()
        flash("Absensi berhasil diperbarui.", "success")
        return redirect(url_for("absensi", tanggal=tanggal.isoformat()))

    return render_template("edit_absensi.html", absensi=absensi_obj,
                           daftar_karyawan=daftar_karyawan)


@app.route("/absensi/hapus/<int:id>", methods=["POST"])
@login_required
def hapus_absensi(id):
    absensi_obj = db.session.get(Absensi, id)
    if not absensi_obj:
        return "Data absensi tidak ditemukan", 404
    tanggal = absensi_obj.tanggal
    db.session.delete(absensi_obj)
    db.session.commit()
    flash("Data absensi dihapus. Jika hari ditutup lagi, statusnya akan menjadi Tidak Masuk.", "success")
    return redirect(url_for("absensi", tanggal=tanggal.isoformat()))


# ============================================================
# PENGAJUAN SAKIT / IZIN
# ============================================================

@app.route("/pengajuan")
@login_required
def pengajuan():
    daftar = Pengajuan.query.options(joinedload(Pengajuan.karyawan)).order_by(
        Pengajuan.tanggal.desc(), Pengajuan.id.desc()
    ).all()
    return render_template("pengajuan.html", daftar_pengajuan=daftar)


@app.route("/pengajuan/tambah", methods=["GET", "POST"])
@login_required
def tambah_pengajuan():

    from datetime import datetime

    daftar_karyawan = Karyawan.query.filter_by(
        status_aktif=True
    ).order_by(
        Karyawan.nama.asc()
    ).all()

    if request.method == "POST":

        karyawan_id = request.form.get("karyawan_id")
        tanggal = request.form.get("tanggal")
        jenis = request.form.get("jenis")
        alasan = request.form.get("alasan", "").strip()

        file = request.files.get("bukti")

        # =========================
        # VALIDASI DASAR
        # =========================

        if not karyawan_id:
            return render_template(
                "tambah_pengajuan.html",
                daftar_karyawan=daftar_karyawan,
                error="Karyawan harus dipilih."
            )

        if jenis not in ["Sakit", "Izin"]:
            return render_template(
                "tambah_pengajuan.html",
                daftar_karyawan=daftar_karyawan,
                error="Jenis pengajuan tidak valid."
            )

        if not tanggal:
            return render_template(
                "tambah_pengajuan.html",
                daftar_karyawan=daftar_karyawan,
                error="Tanggal harus diisi."
            )

        if not alasan:
            return render_template(
                "tambah_pengajuan.html",
                daftar_karyawan=daftar_karyawan,
                error="Alasan harus diisi."
            )

        # =========================
        # BUKTI SAKIT WAJIB
        # =========================

        if jenis == "Sakit":
            if not file or not file.filename:
                return render_template(
                    "tambah_pengajuan.html",
                    daftar_karyawan=daftar_karyawan,
                    error="Bukti sakit wajib dilampirkan."
                )

        # =========================
        # UBAH TANGGAL
        # =========================

        try:
            tanggal_obj = datetime.strptime(
                tanggal,
                "%Y-%m-%d"
            ).date()
        except ValueError:
            return render_template(
                "tambah_pengajuan.html",
                daftar_karyawan=daftar_karyawan,
                error="Format tanggal tidak valid."
            )

        # =========================
        # CEK ABSENSI
        # =========================

        absensi_lama = Absensi.query.filter_by(
            karyawan_id=int(karyawan_id),
            tanggal=tanggal_obj
        ).first()

        if absensi_lama:
            return render_template(
                "tambah_pengajuan.html",
                daftar_karyawan=daftar_karyawan,
                error="Karyawan tersebut sudah memiliki absensi pada tanggal tersebut."
            )

        # =========================
        # UPLOAD BUKTI
        # =========================

        nama_file = None

        if file and file.filename:

            if not file_diizinkan(file.filename):
                return render_template(
                    "tambah_pengajuan.html",
                    daftar_karyawan=daftar_karyawan,
                    error="Format file harus PDF, JPG, JPEG, atau PNG."
                )

            ekstensi = file.filename.rsplit(
                ".",
                1
            )[1].lower()

            nama_file = (
                str(uuid.uuid4())
                + "."
                + ekstensi
            )

            os.makedirs(
                app.config["UPLOAD_FOLDER"],
                exist_ok=True
            )

            lokasi_file = os.path.join(
                app.config["UPLOAD_FOLDER"],
                nama_file
            )

            file.save(lokasi_file)

        # =========================
        # SIMPAN PENGAJUAN
        # =========================

        pengajuan_baru = Pengajuan(
            karyawan_id=int(karyawan_id),
            tanggal=tanggal_obj,
            jenis=jenis,
            alasan=alasan,
            bukti=nama_file,
            status="Disetujui"
        )

        absensi_baru = Absensi(
            karyawan_id=int(karyawan_id),
            tanggal=tanggal_obj,
            status=jenis,
            keterangan=alasan
        )

        db.session.add(absensi_baru)
        db.session.flush()
        pengajuan_baru.absensi_id = absensi_baru.id
        db.session.add(pengajuan_baru)

        db.session.commit()

        return redirect(
            url_for("pengajuan")
        )

    return render_template(
        "tambah_pengajuan.html",
        daftar_karyawan=daftar_karyawan
    )

@app.route("/pengajuan/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_pengajuan(id):

    pengajuan_obj = db.session.get(Pengajuan, id)

    if not pengajuan_obj:
        return "Data pengajuan tidak ditemukan", 404

    daftar_karyawan = Karyawan.query.filter_by(
        status_aktif=True
    ).order_by(
        Karyawan.nama.asc()
    ).all()

    if request.method == "POST":

        karyawan_id = request.form.get("karyawan_id")
        tanggal = request.form.get("tanggal")
        jenis = request.form.get("jenis")
        alasan = request.form.get("alasan", "").strip()

        file = request.files.get("bukti")

        # =========================
        # VALIDASI
        # =========================

        if not karyawan_id:
            return render_template(
                "edit_pengajuan.html",
                pengajuan=pengajuan_obj,
                daftar_karyawan=daftar_karyawan,
                error="Karyawan harus dipilih."
            )

        if jenis not in ["Sakit", "Izin"]:
            return render_template(
                "edit_pengajuan.html",
                pengajuan=pengajuan_obj,
                daftar_karyawan=daftar_karyawan,
                error="Jenis pengajuan tidak valid."
            )

        if not tanggal:
            return render_template(
                "edit_pengajuan.html",
                pengajuan=pengajuan_obj,
                daftar_karyawan=daftar_karyawan,
                error="Tanggal harus diisi."
            )

        if not alasan:
            return render_template(
                "edit_pengajuan.html",
                pengajuan=pengajuan_obj,
                daftar_karyawan=daftar_karyawan,
                error="Alasan harus diisi."
            )

        # =========================
        # BUKTI SAKIT WAJIB
        # =========================

        if jenis == "Sakit":

            # Kalau tidak upload file baru
            # tetapi sudah ada bukti lama,
            # tetap dianggap valid.
            if (
                (not file or not file.filename)
                and not pengajuan_obj.bukti
            ):
                return render_template(
                    "edit_pengajuan.html",
                    pengajuan=pengajuan_obj,
                    daftar_karyawan=daftar_karyawan,
                    error="Bukti sakit wajib dilampirkan."
                )

        # =========================
        # CEK TANGGAL
        # =========================

        tanggal_obj = parse_date(tanggal)

        if not tanggal_obj:
            return render_template(
                "edit_pengajuan.html",
                pengajuan=pengajuan_obj,
                daftar_karyawan=daftar_karyawan,
                error="Tanggal tidak valid."
            )

        # Gunakan relasi eksplisit agar absensi lama tetap ditemukan saat
        # karyawan atau tanggal pengajuan diubah.
        absensi_terkait = pengajuan_obj.absensi_terkait
        if not absensi_terkait:
            absensi_terkait = Absensi.query.filter_by(
                karyawan_id=pengajuan_obj.karyawan_id,
                tanggal=pengajuan_obj.tanggal,
                status=pengajuan_obj.jenis,
            ).first()

        absensi_di_tujuan = Absensi.query.filter_by(
            karyawan_id=int(karyawan_id),
            tanggal=tanggal_obj,
        ).first()
        if absensi_di_tujuan and (
            not absensi_terkait or absensi_di_tujuan.id != absensi_terkait.id
        ):
            return render_template(
                "edit_pengajuan.html",
                pengajuan=pengajuan_obj,
                daftar_karyawan=daftar_karyawan,
                error="Karyawan tersebut sudah memiliki absensi pada tanggal tersebut."
            )

        # =========================
        # UPLOAD BUKTI BARU
        # =========================

        nama_file = pengajuan_obj.bukti

        if file and file.filename:

            if not file_diizinkan(file.filename):
                return render_template(
                    "edit_pengajuan.html",
                    pengajuan=pengajuan_obj,
                    daftar_karyawan=daftar_karyawan,
                    error="Format file harus PDF, JPG, JPEG, atau PNG."
                )

            ekstensi = file.filename.rsplit(
                ".",
                1
            )[1].lower()

            nama_file_baru = (
                str(uuid.uuid4())
                + "."
                + ekstensi
            )

            lokasi_file = os.path.join(
                app.config["UPLOAD_FOLDER"],
                nama_file_baru
            )

            file.save(lokasi_file)

            # Hapus bukti lama jika ada
            if pengajuan_obj.bukti:

                file_lama = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    pengajuan_obj.bukti
                )

                if os.path.exists(file_lama):
                    try:
                        os.remove(file_lama)
                    except OSError:
                        pass

            nama_file = nama_file_baru

        # =========================
        # JIKA DIUBAH MENJADI IZIN
        # =========================

        if jenis == "Izin":

            # Bukti lama tetap boleh disimpan.
            # Kalau mau menghapus bukti,
            # admin bisa upload file baru atau
            # nanti kita tambahkan tombol hapus bukti.

            pass

        # =========================
        # UPDATE PENGAJUAN
        # =========================

        if absensi_terkait:
            absensi_terkait.karyawan_id = int(karyawan_id)
            absensi_terkait.tanggal = tanggal_obj
            absensi_terkait.status = jenis
            absensi_terkait.keterangan = alasan
            absensi_terkait.jam_masuk = None
            absensi_terkait.jam_pulang = None
        else:
            absensi_terkait = Absensi(
                karyawan_id=int(karyawan_id),
                tanggal=tanggal_obj,
                status=jenis,
                keterangan=alasan,
            )
            db.session.add(absensi_terkait)
            db.session.flush()

        pengajuan_obj.karyawan_id = int(karyawan_id)
        pengajuan_obj.tanggal = tanggal_obj
        pengajuan_obj.jenis = jenis
        pengajuan_obj.alasan = alasan
        pengajuan_obj.bukti = nama_file
        pengajuan_obj.absensi_id = absensi_terkait.id

        db.session.commit()

        flash(
            "Data pengajuan berhasil diperbarui.",
            "success"
        )

        return redirect(
            url_for("pengajuan")
        )

    return render_template(
        "edit_pengajuan.html",
        pengajuan=pengajuan_obj,
        daftar_karyawan=daftar_karyawan
    )


@app.route("/pengajuan/<int:id>/bukti")
@login_required
def lihat_bukti(id):
    pengajuan_obj = db.session.get(Pengajuan, id)
    if not pengajuan_obj or not pengajuan_obj.bukti:
        return "Bukti tidak ditemukan", 404
    return send_from_directory(app.config["UPLOAD_FOLDER"], pengajuan_obj.bukti)


@app.route("/pengajuan/<int:id>/bukti/download")
@login_required
def download_bukti(id):
    pengajuan_obj = db.session.get(Pengajuan, id)
    if not pengajuan_obj or not pengajuan_obj.bukti:
        return "Bukti tidak ditemukan", 404
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], pengajuan_obj.bukti, as_attachment=True
    )


@app.route("/pengajuan/hapus/<int:id>", methods=["POST"])
@login_required
def hapus_pengajuan(id):
    pengajuan_obj = db.session.get(Pengajuan, id)
    if not pengajuan_obj:
        return "Data pengajuan tidak ditemukan", 404

    nama_file = pengajuan_obj.bukti
    db.session.delete(pengajuan_obj)
    db.session.commit()

    if nama_file:
        lokasi_file = os.path.join(app.config["UPLOAD_FOLDER"], nama_file)
        if os.path.isfile(lokasi_file):
            try:
                os.remove(lokasi_file)
            except OSError:
                pass

    flash("Pengajuan dihapus. Catatan absensi tetap tersimpan.", "success")
    return redirect(url_for("pengajuan"))


# ============================================================
# LEMBUR
# ============================================================

@app.route("/lembur")
@login_required
def lembur():
    daftar = Lembur.query.options(
        joinedload(Lembur.absensi).joinedload(Absensi.karyawan)
    ).order_by(Lembur.id.desc()).all()
    total_jam = round(sum((item.total_jam or 0) for item in daftar), 2)
    return render_template("lembur.html", daftar_lembur=daftar, total_jam=total_jam)


@app.route("/lembur/tambah", methods=["GET", "POST"])
@login_required
def tambah_lembur():
    daftar_absensi = Absensi.query.filter_by(status="Masuk").order_by(
        Absensi.tanggal.desc(), Absensi.id.desc()
    ).all()

    if request.method == "POST":
        absensi_id = request.form.get("absensi_id")
        jam_mulai = parse_time(request.form.get("jam_mulai"))
        jam_selesai = parse_time(request.form.get("jam_selesai"))
        keterangan = request.form.get("keterangan", "").strip()

        if not absensi_id or not jam_mulai or not jam_selesai:
            return render_template("tambah_lembur.html", daftar_absensi=daftar_absensi,
                                   error="Absensi, jam mulai, dan jam selesai wajib diisi.")

        absensi_obj = db.session.get(Absensi, int(absensi_id))
        if not absensi_obj or absensi_obj.status != "Masuk":
            return render_template("tambah_lembur.html", daftar_absensi=daftar_absensi,
                                   error="Lembur hanya dapat diberikan untuk absensi berstatus Masuk.")
        if Lembur.query.filter_by(absensi_id=absensi_obj.id).first():
            return render_template("tambah_lembur.html", daftar_absensi=daftar_absensi,
                                   error="Absensi tersebut sudah memiliki data lembur.")

        mulai = jam_mulai.hour * 60 + jam_mulai.minute
        selesai = jam_selesai.hour * 60 + jam_selesai.minute
        if selesai < mulai:
            selesai += 24 * 60
        total = round((selesai - mulai) / 60, 2)
        if total <= 0:
            return render_template("tambah_lembur.html", daftar_absensi=daftar_absensi,
                                   error="Durasi lembur harus lebih dari 0 jam.")

        db.session.add(Lembur(absensi_id=absensi_obj.id, jam_mulai=jam_mulai,
                              jam_selesai=jam_selesai, total_jam=total,
                              keterangan=keterangan))
        db.session.commit()
        flash(f"Lembur {absensi_obj.karyawan.nama} berhasil dicatat: {total:g} jam.", "success")
        return redirect(url_for("lembur"))

    return render_template("tambah_lembur.html", daftar_absensi=daftar_absensi)


@app.route("/lembur/hapus/<int:id>", methods=["POST"])
@login_required
def hapus_lembur(id):
    obj = db.session.get(Lembur, id)
    if not obj:
        return "Data lembur tidak ditemukan", 404
    db.session.delete(obj)
    db.session.commit()
    flash("Data lembur dihapus.", "success")
    return redirect(url_for("lembur"))


# ============================================================
# LAPORAN + PDF
# ============================================================

@app.route("/laporan")
@login_required
def laporan():
    tanggal_mulai = parse_date(request.args.get("tanggal_mulai"))
    tanggal_selesai = parse_date(request.args.get("tanggal_selesai"))
    daftar = []
    if tanggal_mulai and tanggal_selesai and tanggal_mulai <= tanggal_selesai:
        daftar = absensi_untuk_laporan(tanggal_mulai, tanggal_selesai)

    rekap = {
        "Masuk": sum(1 for x in daftar if x.status == "Masuk"),
        "Sakit": sum(1 for x in daftar if x.status == "Sakit"),
        "Izin": sum(1 for x in daftar if x.status == "Izin"),
        "Tidak Masuk": sum(1 for x in daftar if x.status == "Tidak Masuk"),
    }
    return render_template("laporan.html", daftar_absensi=daftar,
                           tanggal_mulai=tanggal_mulai, tanggal_selesai=tanggal_selesai,
                           rekap=rekap)


@app.route("/laporan/pdf")
@login_required
def laporan_pdf():
    tanggal_mulai = parse_date(request.args.get("tanggal_mulai"))
    tanggal_selesai = parse_date(request.args.get("tanggal_selesai"))
    if not tanggal_mulai or not tanggal_selesai or tanggal_mulai > tanggal_selesai:
        return "Tanggal laporan tidak valid.", 400

    daftar = absensi_untuk_laporan(tanggal_mulai, tanggal_selesai)
    rekap = {
        "Masuk": sum(1 for x in daftar if x.status == "Masuk"),
        "Sakit": sum(1 for x in daftar if x.status == "Sakit"),
        "Izin": sum(1 for x in daftar if x.status == "Izin"),
        "Tidak Masuk": sum(1 for x in daftar if x.status == "Tidak Masuk"),
    }

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            rightMargin=22, leftMargin=22, topMargin=25, bottomMargin=25)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ReportTitle", parent=styles["Title"], alignment=TA_CENTER, fontSize=16)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=7, leading=9)

    isi = [
        Paragraph("LAPORAN ABSENSI KARYAWAN", title),
        Paragraph(f"Periode: {format_tanggal(tanggal_mulai)} s/d {format_tanggal(tanggal_selesai)}", styles["Normal"]),
        Spacer(1, 10),
    ]

    rekap_table = Table([
        ["Masuk", "Sakit", "Izin", "Tidak Masuk"],
        [str(rekap["Masuk"]), str(rekap["Sakit"]), str(rekap["Izin"]), str(rekap["Tidak Masuk"])]
    ], colWidths=[110, 110, 110, 120])
    rekap_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), .5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    isi += [rekap_table, Spacer(1, 12)]

    rows = [["No", "Tanggal", "NIK", "Nama", "Jabatan", "Departemen", "Masuk", "Pulang", "Status", "Keterangan", "Lembur"]]
    for no, item in enumerate(daftar, 1):
        rows.append([
            str(no), format_tanggal(item.tanggal), item.karyawan.nik, item.karyawan.nama,
            item.karyawan.jabatan, item.karyawan.departemen or "-",
            item.jam_masuk.strftime("%H:%M") if item.jam_masuk else "-",
            item.jam_pulang.strftime("%H:%M") if item.jam_pulang else "-",
            item.status, Paragraph((item.keterangan or "-")[:120], small),
            f"{item.lembur.total_jam:g} jam" if item.lembur and item.lembur.total_jam is not None else "-"
        ])

    table = Table(rows, repeatRows=1,
                  colWidths=[23, 55, 52, 82, 72, 70, 42, 42, 58, 125, 50])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("GRID", (0, 0), (-1, -1), .35, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (6, 1), (8, -1), "CENTER"),
        ("ALIGN", (10, 1), (10, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    isi.append(table)
    doc.build(isi)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"laporan_absensi_{tanggal_mulai}_{tanggal_selesai}.pdf",
                     mimetype="application/pdf")


# ============================================================
# BACKUP + PENGATURAN
# ============================================================

@app.route("/backup/database")
@login_required
def backup_database():
    db_path = os.path.join(app.instance_path, "database.db")
    if not os.path.exists(db_path):
        return "Database tidak ditemukan.", 404

    # Pastikan database WAL tersinkron sebelum dibaca sebagai backup.
    try:
        db.session.execute(db.text("PRAGMA wal_checkpoint(FULL)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    with open(db_path, "rb") as f:
        data = f.read()

    return send_file(BytesIO(data), as_attachment=True,
                     download_name=f"backup_absensi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                     mimetype="application/octet-stream")


@app.route("/pengaturan", methods=["GET", "POST"])
@login_required
def pengaturan():
    if request.method == "POST":
        password_lama = request.form.get("password_lama", "")
        password_baru = request.form.get("password_baru", "")
        konfirmasi = request.form.get("konfirmasi", "")
        admin = db.session.get(Admin, current_user.id)

        if not admin or not check_password_hash(admin.password, password_lama):
            flash("Password lama salah.", "error")
        elif len(password_baru) < 6:
            flash("Password baru minimal 6 karakter.", "error")
        elif password_baru != konfirmasi:
            flash("Konfirmasi password tidak sama.", "error")
        else:
            admin.password = generate_password_hash(password_baru)
            db.session.commit()
            flash("Password admin berhasil diubah.", "success")
            return redirect(url_for("pengaturan"))

    db_path = os.path.join(app.instance_path, "database.db")
    ukuran = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    return render_template("pengaturan.html", ukuran_db=ukuran,
                           jumlah_karyawan=Karyawan.query.count(),
                           jumlah_absensi=Absensi.query.count(),
                           jumlah_pengajuan=Pengajuan.query.count(),
                           jumlah_lembur=Lembur.query.count())



# ============================================================
# INIT DATABASE
# ============================================================


def siapkan_skema_database():
    """Migrasi ringan dan idempoten untuk database instalasi lama."""
    with db.engine.begin() as koneksi:
        tabel = {
            row[0]
            for row in koneksi.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ))
        }

        if "pengajuan" in tabel:
            kolom_pengajuan = {
                row[1] for row in koneksi.execute(text("PRAGMA table_info(pengajuan)"))
            }
            if "absensi_id" not in kolom_pengajuan:
                koneksi.execute(text("ALTER TABLE pengajuan ADD COLUMN absensi_id INTEGER"))

    db.create_all()

    with db.engine.begin() as koneksi:
        duplikat_absensi = koneksi.execute(text("""
            SELECT karyawan_id, tanggal
            FROM absensi
            GROUP BY karyawan_id, tanggal
            HAVING COUNT(*) > 1
            LIMIT 1
        """)).first()
        duplikat_lembur = koneksi.execute(text("""
            SELECT absensi_id
            FROM lembur
            GROUP BY absensi_id
            HAVING COUNT(*) > 1
            LIMIT 1
        """)).first()
        duplikat_pengajuan = koneksi.execute(text("""
            SELECT karyawan_id, tanggal
            FROM pengajuan
            GROUP BY karyawan_id, tanggal
            HAVING COUNT(*) > 1
            LIMIT 1
        """)).first()

        if duplikat_absensi or duplikat_lembur or duplikat_pengajuan:
            raise RuntimeError(
                "Database memiliki data duplikat. Buat backup lalu rapikan data sebelum aplikasi dijalankan."
            )

        # Hubungkan pengajuan lama dengan record absensi yang dibuat bersamanya.
        koneksi.execute(text("""
            UPDATE pengajuan
            SET absensi_id = (
                SELECT a.id
                FROM absensi AS a
                WHERE a.karyawan_id = pengajuan.karyawan_id
                  AND a.tanggal = pengajuan.tanggal
                  AND a.status = pengajuan.jenis
                LIMIT 1
            )
            WHERE absensi_id IS NULL
        """))

        indeks = [
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_absensi_karyawan_tanggal ON absensi(karyawan_id, tanggal)",
            "CREATE INDEX IF NOT EXISTS ix_absensi_tanggal ON absensi(tanggal)",
            "CREATE INDEX IF NOT EXISTS ix_absensi_status ON absensi(status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_lembur_absensi ON lembur(absensi_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_pengajuan_karyawan_tanggal ON pengajuan(karyawan_id, tanggal)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_pengajuan_absensi ON pengajuan(absensi_id) WHERE absensi_id IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS ix_pengajuan_tanggal ON pengajuan(tanggal)",
            "CREATE INDEX IF NOT EXISTS ix_pengajuan_status ON pengajuan(status)",
            "CREATE INDEX IF NOT EXISTS ix_karyawan_nama ON karyawan(nama)",
            "CREATE INDEX IF NOT EXISTS ix_karyawan_status_aktif ON karyawan(status_aktif)",
        ]
        for perintah in indeks:
            koneksi.execute(text(perintah))

        # Database lama tidak bisa menerima foreign key baru melalui ALTER TABLE.
        # Trigger ini menjaga relasi pengajuan -> absensi tetap valid.
        koneksi.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_pengajuan_absensi_insert
            BEFORE INSERT ON pengajuan
            WHEN NEW.absensi_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM absensi WHERE id = NEW.absensi_id)
            BEGIN
                SELECT RAISE(ABORT, 'absensi_id tidak valid');
            END
        """))
        koneksi.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_pengajuan_absensi_update
            BEFORE UPDATE OF absensi_id ON pengajuan
            WHEN NEW.absensi_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM absensi WHERE id = NEW.absensi_id)
            BEGIN
                SELECT RAISE(ABORT, 'absensi_id tidak valid');
            END
        """))
        koneksi.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_absensi_hapus_pengajuan
            AFTER DELETE ON absensi
            BEGIN
                UPDATE pengajuan SET absensi_id = NULL WHERE absensi_id = OLD.id;
            END
        """))


with app.app_context():
    siapkan_skema_database()


if __name__ == "__main__":
    host = os.environ.get("ABSENSI_HOST", "127.0.0.1")
    port = int(os.environ.get("ABSENSI_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
